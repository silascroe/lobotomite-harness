// Pure derivations from harness records. Nothing here touches the DOM, so the
// console, the showcase and the tests all read runs the same way.

export const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export const LEVELS = ["off", "low", "standard", "deep"];
export const LEVEL_LABEL = { off: "Off", low: "Low", standard: "Standard", deep: "Deep" };
export const PHASES = ["intake", "inspect", "design", "plan", "implement", "verify", "review", "complete", "blocked"];
const TERMINAL = new Set(["success", "complete", "blocked", "error", "failed", "aborted"]);

export const TOOL_GLYPH = {
  list_files: "L", read_file: "R", write_file: "W", replace_text: "E", apply_patch: "P", delete_file: "−",
  run_command: "$", git_diff: "Δ", workflow_checkpoint: "C", find_skills: "S",
};
export const TOOL_LABEL = {
  list_files: "list", read_file: "read", write_file: "write", replace_text: "replace", apply_patch: "patch", delete_file: "delete",
  run_command: "run", git_diff: "diff", workflow_checkpoint: "checkpoint", find_skills: "skills",
};
const EDIT_TOOLS = new Set(["write_file", "replace_text", "apply_patch", "delete_file"]);

export function clock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

export const num = (n) => (n == null || Number.isNaN(Number(n)) ? "–" : Number(n).toLocaleString("en-US"));

export function taskTitle(profileOrName) {
  const raw = typeof profileOrName === "string" ? profileOrName : profileOrName?.title || profileOrName?.name || "";
  if (!raw) return "Custom task";
  const known = { "001": "Static page", "002": "File round-trip", "003": "Structured validation", "004": "Mini project" };
  const prefix = String(raw).slice(0, 3);
  if (/^\d{3}-/.test(raw) && known[prefix]) return known[prefix];
  return String(raw).replace(/ smoke test$/i, "").replace(/\.md$/, "");
}

export function toolFailed(action, result) {
  return result?.ok === false || Boolean(result?.error) || (action === "run_command" && Boolean(result?.exit_code));
}

function parseChecks(result) {
  if (result?.checks && typeof result.checks === "object") return result.checks;
  try {
    const parsed = JSON.parse(result?.stdout || "{}");
    return parsed && typeof parsed.checks === "object" ? parsed.checks : null;
  } catch {
    return null;
  }
}

function parseFindings(result) {
  if (Array.isArray(result?.findings)) return result.findings;
  try {
    const parsed = JSON.parse(result?.stdout || "{}");
    return Array.isArray(parsed?.findings) ? parsed.findings : [];
  } catch {
    return [];
  }
}

/* ---------- patch parsing: mirrors the harness's apply_update matching ---------- */

export function patchTargets(patch) {
  const out = [];
  for (const line of String(patch || "").split(/\r?\n/)) {
    const m = line.match(/^\*\*\* (Update|Add|Delete) File: (.+)$/);
    if (m) out.push({ op: m[1].toLowerCase(), path: m[2].trim() });
  }
  return out;
}

function patchHunks(patch, path) {
  // Collect the hunks belonging to one file, using the harness's leniency:
  // plain lines count as context, blank lines as an empty context line.
  const lines = String(patch || "").split(/\r?\n/);
  const hunks = [];
  let inFile = false;
  let header = "@@";
  let body = [];
  const flush = () => { if (body.length) hunks.push({ header, body }); body = []; };
  for (const line of lines) {
    const file = line.match(/^\*\*\* (Update|Add|Delete) File: (.+)$/);
    if (file) { if (inFile) flush(); inFile = file[2].trim() === path; header = "@@"; continue; }
    if (!inFile || line.startsWith("*** ")) continue;
    if (line.startsWith("@@")) { flush(); header = line; continue; }
    if (line === "\\ No newline at end of file") continue;
    if (/^[ +-]/.test(line)) body.push(line);
    else if (!line.trim()) body.push(" ");
    else body.push(" " + line);
  }
  if (inFile) flush();
  return hunks;
}

/**
 * Replays the harness's apply_update on `content` and returns the hunks it
 * would have placed by line number because their context matched nothing.
 * Hunks are applied in order with the same cursor and wrap-around search, so a
 * later hunk may quote lines an earlier hunk added.
 */
export function patchContextMisses(patch, path, content) {
  if (typeof content !== "string") return null;
  const result = content.split(/\r\n|\n|\r/);
  if (result.length && result[result.length - 1] === "") result.pop();
  const misses = [];
  let cursor = 0;
  const find = (block, from, to) => {
    for (let i = from; i <= to; i++) {
      let ok = true;
      for (let j = 0; j < block.length; j++) if (result[i + j] !== block[j]) { ok = false; break; }
      if (ok) return i;
    }
    return -1;
  };
  for (const { header, body } of patchHunks(patch, path)) {
    let oldBlock = body.filter((l) => l[0] === " " || l[0] === "-").map((l) => l.slice(1));
    let newBlock = body.filter((l) => l[0] === " " || l[0] === "+").map((l) => l.slice(1));
    const additions = body.filter((l) => l[0] === "+").map((l) => l.slice(1));
    let position;
    if (oldBlock.length) {
      position = find(oldBlock, cursor, result.length - oldBlock.length);
      if (position < 0 && cursor) position = find(oldBlock, 0, cursor - 1);
      if (position < 0) {
        const lineNo = (header.match(/-([0-9]+)/) || [])[1];
        if (!(additions.length && !body.some((l) => l[0] === "-")) || !lineNo) return misses; // the harness rejects this patch
        position = Math.min(Math.max(0, Number(lineNo) - 1), result.length);
        misses.push({ header, insertedAt: Number(lineNo), missing: oldBlock.filter((line) => !result.includes(line)).slice(0, 8) });
        oldBlock = [];
        newBlock = additions;
      }
    } else {
      const lineNo = (header.match(/-([0-9]+)/) || [])[1];
      position = lineNo ? Math.max(0, Number(lineNo) - 1) : result.length;
    }
    result.splice(position, oldBlock.length, ...newBlock);
    cursor = position + newBlock.length;
  }
  return misses;
}

const CLIPPED = /\n\.\.\.\[clipped for the showcase/;

/* ---------- the run ---------- */

export function buildRun(events, state = {}) {
  const list = (Array.isArray(events) ? events : []).filter((e) => e && e.event);
  const ts = (e) => Date.parse(e.timestamp);
  const t0 = list.length ? ts(list[0]) : null;
  const rel = (e) => (t0 == null ? 0 : Math.max(0, (ts(e) - t0) / 1000));
  const run = {
    t0, duration: 0, turns: [], tools: [], phases: [], gates: [], evals: [], context: [], approvals: [],
    files: new Map(), repair: null, finish: null, task: "", alarms: [], compactions: 0, dropped: 0,
    maxOutput: Number(state?.reasoning?.max_tokens) || 0,
  };
  const views = new Map(); // path -> the content the model last saw or wrote, when known
  const fileTrack = (path) => {
    if (!run.files.has(path)) run.files.set(path, []);
    return run.files.get(path);
  };
  let turn = null;
  let phase = null;
  const startPhase = (name, at) => {
    if (phase && phase.phase === name) return;
    if (phase) phase.to = at;
    phase = { phase: name, from: at, to: null };
    run.phases.push(phase);
  };

  list.forEach((ev, index) => {
    const d = ev.data || {};
    const at = rel(ev);
    run.duration = Math.max(run.duration, at);
    switch (ev.event) {
      case "run_created":
      case "session_ready":
        if (d.task) run.task = String(d.task);
        break;
      case "model_response": {
        const usage = d.usage || {};
        turn = {
          n: Number(d.turn ?? d.step ?? run.turns.length + 1) || run.turns.length + 1,
          at, end: null, index,
          prompt: Number(usage.prompt_tokens) || 0,
          output: Number(usage.completion_tokens) || 0,
          finish: d.finish_reason || "",
          content: typeof d.content === "string" ? d.content : "",
          tools: [], marks: [],
        };
        if (run.turns.length) run.turns[run.turns.length - 1].end = at;
        run.turns.push(turn);
        break;
      }
      case "tool_result": {
        const action = String(d.action || "");
        const args = d.args || {};
        const result = d.result || {};
        const failed = toolFailed(action, result);
        const tool = {
          turn: Number(d.turn) || turn?.n || 0, at, action, args, result, failed, index,
          glyph: TOOL_GLYPH[action] || "?",
          error: failed ? String(result.error || result.stderr || "the tool reported a failure").trim() : "",
          paths: [], fallback: null,
        };
        if (action === "apply_patch") {
          const targets = patchTargets(args.patch);
          tool.paths = targets.map((t) => t.path);
          for (const target of targets) {
            const view = views.get(target.path) || null;
            let misses = null;
            if (!failed && target.op === "update") {
              misses = result.context_fallback ? [{ header: "", insertedAt: null, missing: [] }] : patchContextMisses(args.patch, target.path, view?.content);
            }
            const kind = failed ? "X" : misses && misses.length ? "P!" : "P";
            tool.view = view;
            if (misses && misses.length) tool.fallback = { path: target.path, misses, before: view?.content ?? null, beforeTurn: view?.turn ?? null, beforeKind: view?.kind ?? null };
            fileTrack(target.path).push({ turn: tool.turn, at, kind, tool });
            views.set(target.path, { content: null, turn: tool.turn, kind: "patch" }); // exact text no longer known
          }
        } else if (["read_file", "write_file", "replace_text", "delete_file"].includes(action)) {
          const path = String(result.path || args.path || "");
          if (path) {
            tool.paths = [path];
            const kind = failed ? "X" : { read_file: "R", write_file: "W", replace_text: "E", delete_file: "−" }[action];
            fileTrack(path).push({ turn: tool.turn, at, kind, tool });
            if (!failed && action === "read_file") {
              const content = typeof result.content === "string" && !result.truncated && !CLIPPED.test(result.content) ? result.content : null;
              views.set(path, { content, turn: tool.turn, kind: "read" });
            } else if (!failed && action === "write_file") {
              const content = typeof args.content === "string" && !CLIPPED.test(args.content) ? args.content : null;
              views.set(path, { content, turn: tool.turn, kind: "write" });
            } else if (!failed) views.set(path, { content: null, turn: tool.turn, kind: action });
          }
        }
        run.tools.push(tool);
        if (turn) turn.tools.push(tool);
        break;
      }
      case "workflow_phase":
        if (d.state?.phase) startPhase(d.state.phase, at);
        break;
      case "finish_rejected": {
        const reason = String(d.reason || "");
        if (reason.startsWith("The external evaluator")) break;
        const missing = Array.isArray(d.missing_gates) ? d.missing_gates : [];
        const label = missing.length ? `finish refused: no ${missing.join(", ")}` : "finish refused";
        run.gates.push({ at, turn: Number(d.turn) || turn?.n, kind: "refused", label, detail: reason.replace(/^success is not accepted yet;\s*/, ""), index, missing });
        break;
      }
      case "evaluator": {
        const result = d.result || {};
        const checks = parseChecks(result) || {};
        const entries = Object.entries(checks);
        const ev2 = {
          at, turn: turn?.n, index, passed: Boolean(result.passed), checks,
          passedCount: entries.filter(([, ok]) => ok).length, total: entries.length,
          findings: parseFindings(result), error: result.error ? String(result.error) : "",
        };
        run.evals.push(ev2);
        run.gates.push({ at, turn: turn?.n, kind: ev2.passed ? "eval-pass" : "eval-fail", label: `evaluator ${ev2.passedCount}/${ev2.total}`, index });
        break;
      }
      case "repair_episode_started":
        run.repair = { ...(d.repair_episode || {}), start: at, end: null };
        break;
      case "repair_rechecked":
        run.repair = { ...(run.repair || {}), ...(d.repair_episode || {}) };
        break;
      case "repair_episode_finished":
        run.repair = { ...(run.repair || { start: at }), ...(d.repair_episode || {}), end: at };
        break;
      case "context_compacted": {
        run.compactions += d.compacted === false ? 0 : 1;
        run.dropped = Math.max(run.dropped, Number(d.dropped_messages) || 0);
        const before = Number(d.before_tokens) || 0;
        const after = Number(d.after_tokens) || 0;
        run.context.push({ at, turn: (turn?.n || 0) + 1, kept: before ? Math.min(1, after / before) : 1, before, after, dropped: Number(d.dropped_messages) || 0 });
        break;
      }
      case "invalid_model_action":
        if (turn) turn.marks.push({ kind: "invalid", error: String(d.error || "") });
        run.gates.push({ at, turn: Number(d.turn) || turn?.n, kind: "invalid", label: "no valid action", detail: String(d.error || ""), index });
        break;
      case "recovery_duplicate_action":
        if (turn) turn.marks.push({ kind: "duplicate", error: String(d.decision?.detail || "") });
        break;
      case "recovery_exhausted":
        run.gates.push({ at, turn: turn?.n, kind: "exhausted", label: "recovery exhausted", detail: String(d.decision?.detail || ""), index });
        break;
      case "turn_limit":
        run.gates.push({ at, turn: turn?.n, kind: "turn-limit", label: "turn limit", detail: `reached the ${d.max_turns ?? ""}-turn limit`, index });
        break;
      case "harness_error":
        run.gates.push({ at, turn: turn?.n, kind: "error", label: "harness error", detail: String(d.error || ""), index });
        break;
      case "approval_requested":
        run.approvals.push({ at, turn: turn?.n, status: "pending", action: d.summary?.action || d.action || "", summary: d.summary || {}, index });
        break;
      case "approval_resolved": {
        const open = [...run.approvals].reverse().find((a) => a.status === "pending");
        if (open) { open.status = d.status || "resolved"; open.resolvedAt = at; }
        break;
      }
      case "finish":
        run.finish = { status: d.status, summary: String(d.summary || ""), at };
        break;
      default:
        break;
    }
  });
  if (phase) phase.to = run.duration;
  if (run.turns.length) run.turns[run.turns.length - 1].end = run.duration;
  if (!run.maxOutput) run.maxOutput = Math.max(0, ...run.turns.map((t) => t.output));
  for (const t of run.turns) t.truncated = Boolean(run.maxOutput) && t.output >= run.maxOutput && (t.finish === "length" || t.marks.some((m) => m.kind === "invalid"));
  run.verdict = verdict(state, run);
  run.alarms = buildAlarms(run, state);
  return run;
}

export function verdict(state = {}, run = null) {
  const summary = state.summary || {};
  const status = String(state.status || summary.status || "");
  const evaluation = typeof summary.evaluation === "object" && summary.evaluation ? summary.evaluation : null;
  const lastEval = run?.evals?.[run.evals.length - 1];
  const checks = lastEval ? { passed: lastEval.passedCount, total: lastEval.total } : null;
  const reason = String(summary.blocked_reason || summary.summary || "");
  const first = summary.first_pass_passed ?? state.first_pass_passed;
  if (status === "success" || status === "complete") {
    const graded = Boolean(evaluation?.configured || lastEval);
    if (!graded) return { key: "finished", word: "FINISHED", tone: "ok", line: "Finished without an external evaluator; nothing checked the result.", checks };
    if (first === false) return { key: "repaired", word: "PASSED", tag: "Passed · repaired", tone: "ok", line: "First evaluation failed; the repair episode fixed it.", checks };
    return { key: "passed", word: "PASSED", tag: "FIRST TRY", tone: "ok", line: "Every check passed on the first evaluation.", checks };
  }
  if (status === "running") return { key: "running", word: "RUNNING", tone: "live", line: "Recording.", checks };
  if (status === "waiting_approval") return { key: "waiting", word: "WAITING", tone: "warn", line: "The next project change is paused until you decide.", checks };
  if (status === "interrupted") return { key: "interrupted", word: "INTERRUPTED", tone: "warn", line: "Resume to continue from the last checkpoint.", checks };
  if (status === "blocked") return { key: "blocked", word: "BLOCKED", tag: failureLabel(failureCode(reason, status)).toUpperCase(), tone: "bad", line: reason || "The run stopped before it could finish.", checks };
  if (status === "error" || status === "failed") return { key: "error", word: "ERROR", tone: "bad", line: reason || "The run stopped on an error.", checks };
  if (status === "aborted") return { key: "aborted", word: "ABORTED", tone: "warn", line: "The run ended without a summary.", checks };
  return { key: status || "unknown", word: (status || "UNKNOWN").toUpperCase(), tone: "warn", line: reason, checks };
}

/* ---------- failure codes (bench + verdict) ---------- */

export const FAILURE_CODES = {
  E: "edit tool exhausted its retries",
  R: "repair budget spent",
  D: "stopped for repeating an action",
  T: "turn limit",
  W: "workflow checkpoint rejected",
  G: "finish gate refused",
  F: "other tool failed",
  B: "model declared itself blocked",
  O: "timed out",
  "?": "other",
};

export function failureCode(cause = "", status = "") {
  const c = String(cause).toLowerCase();
  if (/repair extension exhausted|repair budget/.test(c)) return "R";
  if (/tool_failure[^:]*:\s*(apply_patch|replace_text)/.test(c) || /^(apply_patch|replace_text):/.test(c)) return "E";
  if (/duplicate_action|repeated .* with the same/.test(c)) return "D";
  if (/turn limit|-turn limit/.test(c)) return "T";
  if (/workflow_checkpoint|cannot transition/.test(c)) return "W";
  if (/finish_rejected|not accepted yet/.test(c)) return "G";
  if (/tool_failure/.test(c)) return "F";
  if (/timed out|timeout/.test(c)) return "O";
  if (status === "blocked" && c) return "B";
  return "?";
}

export function failureLabel(code) {
  return FAILURE_CODES[code] || FAILURE_CODES["?"];
}

/* ---------- alarms (ISA-18.2 style: priority, tag, state) ---------- */

function buildAlarms(run, state) {
  const alarms = [];
  const lastAt = run.duration;
  const terminal = TERMINAL.has(String(state.status || state.summary?.status || "")) && !["success", "complete"].includes(String(state.status || ""));
  const later = (index) => run.turns.some((t) => t.index > index);
  const push = (a) => alarms.push({ state: "RTN", ...a });
  for (const g of run.gates) {
    if (g.kind === "refused") push({ pri: 3, at: g.at, turn: g.turn, tag: `GATE.${(g.missing?.[0] || "FINISH").toUpperCase()}`, text: g.label.replace(/^finish refused/, "Finish refused"), state: later(g.index) ? "RTN" : "ACTIVE" });
    if (g.kind === "invalid") {
      const t = run.turns.find((x) => x.n === g.turn);
      const capped = t?.truncated;
      push({ pri: 2, at: g.at, turn: g.turn, tag: "MODEL.OUT", text: capped ? `Output hit the ${num(t.output)}-token cap with no valid action` : `No valid action: ${g.detail}`, state: later(g.index) ? "RTN" : "ACTIVE" });
    }
    if (g.kind === "eval-fail") {
      const ev = run.evals.find((e) => e.index === g.index);
      const failing = ev ? Object.entries(ev.checks).filter(([, ok]) => !ok).map(([k]) => k) : [];
      const fixed = run.evals.some((e) => e.index > g.index && e.passed);
      push({ pri: 2, at: g.at, turn: g.turn, tag: "EVAL.CHECKS", text: `Evaluator ${ev?.passedCount}/${ev?.total}: ${failing.join(", ")}`, state: fixed ? "RTN" : "ACTIVE" });
    }
    if (g.kind === "exhausted") push({ pri: 1, at: g.at, turn: g.turn, tag: "RUN.RECOVERY", text: `Recovery exhausted: ${g.detail}`, state: "LATCHED" });
    if (g.kind === "turn-limit") push({ pri: 1, at: g.at, turn: g.turn, tag: "RUN.TURNS", text: g.detail || "Turn limit reached", state: "LATCHED" });
    if (g.kind === "error") push({ pri: 1, at: g.at, turn: g.turn, tag: "RUN.ERROR", text: g.detail, state: "LATCHED" });
  }
  for (const t of run.tools) {
    if (t.failed) push({ pri: 2, at: t.at, turn: t.turn, tag: `TOOL.${(TOOL_LABEL[t.action] || t.action).toUpperCase()}`, text: `${t.action}${t.paths[0] ? ` on ${t.paths[0]}` : ""}: ${t.error}`, state: later(t.index) ? "RTN" : "ACTIVE" });
    if (t.fallback) push({ pri: 2, at: t.at, turn: t.turn, tag: "EDIT.FALLBACK", text: `apply_patch on ${t.fallback.path} reported ok, but its context matched nothing; the added lines went in by line number`, state: "ACTIVE" });
  }
  if (run.repair && run.repair.end != null && run.repair.status !== "passed") {
    push({ pri: 1, at: run.repair.end, turn: null, tag: "RUN.REPAIR", text: `Repair ${String(run.repair.status || "stopped").replace(/_/g, " ")}: ${run.repair.extension_turns_used ?? "?"} of ${run.repair.extension_limit ?? 6} extra calls used`, state: "LATCHED" });
  }
  for (const a of run.approvals) push({ pri: 2, at: a.at, turn: a.turn, tag: "OPS.APPROVAL", text: `Approval ${a.status === "pending" ? "requested" : a.status} for ${a.action}`, state: a.status === "pending" ? "UNACK" : "RTN" });
  if (!terminal) for (const a of alarms) if (a.state === "LATCHED") a.state = "ACTIVE";
  if (["success", "complete"].includes(String(state.status || ""))) for (const a of alarms) if (a.state === "ACTIVE") a.state = "RTN";
  alarms.sort((a, b) => b.at - a.at || a.pri - b.pri);
  void lastAt;
  return alarms;
}

/* ---------- process view ---------- */

export function buildProcess(state = {}, run) {
  const summary = state.summary || {};
  const evidence = summary.workflow_evidence || state.progress?.workflow_evidence || null;
  const seen = new Set(run.phases.map((p) => p.phase));
  const has = (p) => (evidence && p in evidence ? Boolean(evidence[p]) : seen.has(p));
  const current = state.workflow?.phase || run.phases[run.phases.length - 1]?.phase || "intake";
  const lastEval = run.evals[run.evals.length - 1];
  const status = String(state.status || "");
  const done = status === "success" || status === "complete";
  const unit = (id, name, tag, kind, note) => ({ id, name, tag, kind, note });
  const evidenceUnit = (p, tag) => unit(p, p.toUpperCase(), tag, current === p && !done ? "current" : has(p) ? "done" : "open", has(p) ? "evidence recorded" : "no evidence");
  const units = [
    evidenceUnit("inspect", "IN-1"),
    unit("design", "DESIGN", "DS-1", seen.has("design") ? "done" : "skip", seen.has("design") ? "evidence recorded" : "optional"),
    evidenceUnit("plan", "PL-1"),
    evidenceUnit("implement", "IM-1"),
    evidenceUnit("verify", "VF-1"),
    evidenceUnit("review", "RV-1"),
    unit("gate", "FINISH GATE", "XV-1", done ? "open-valve" : "valve", done ? "opened" : run.gates.some((g) => g.kind === "refused") ? "refused a finish" : "closed"),
    unit("eval", "EVALUATOR", "EV-1", !lastEval ? "open" : lastEval.passed ? "done" : "alarm", lastEval ? `${lastEval.passedCount} / ${lastEval.total} checks` : "not reached"),
    unit("complete", "COMPLETE", "CP-1", done ? "done" : "open", done ? "accepted" : "not reached"),
  ];
  const repair = run.repair ? { used: run.repair.extension_turns_used ?? 0, limit: run.repair.extension_limit ?? 6, status: run.repair.status || "active" } : null;
  return { units, repair, current };
}

/* ---------- chats ---------- */

export function chatGroups(events) {
  const list = (Array.isArray(events) ? events : []).filter((e) => e && e.event);
  const groups = [];
  let current = { tools: [], calls: 0, start: null, marks: [] };
  for (const ev of list) {
    const d = ev.data || {};
    const at = Date.parse(ev.timestamp);
    if (ev.event === "model_response") { current.calls += 1; if (current.start == null) current.start = at; }
    if (ev.event === "tool_result") {
      const action = String(d.action || "");
      const result = d.result || {};
      const failed = toolFailed(action, result);
      current.tools.push({ action, glyph: TOOL_GLYPH[action] || "?", failed, path: result.path || d.args?.path || d.args?.command || "", error: failed ? String(result.error || result.stderr || "") : "" });
    }
    if (ev.event === "invalid_model_action" || ev.event === "recovery_duplicate_action" || ev.event === "recovery_exhausted") {
      current.marks.push(ev.event === "invalid_model_action" ? "no valid action" : ev.event === "recovery_exhausted" ? "recovery exhausted" : "repeated action");
    }
    if (ev.event === "assistant_message") {
      groups.push({ ...current, seconds: current.start == null ? 0 : (at - current.start) / 1000 });
      current = { tools: [], calls: 0, start: null, marks: [] };
    }
  }
  return { groups, live: current };
}

export function chatTitle(conversation, fallback = "New chat") {
  const first = (conversation || []).find((m) => m.role === "user" && String(m.content || "").trim());
  if (!first) return fallback;
  const line = String(first.content).trim().split(/\r?\n/)[0];
  return line.length > 72 ? `${line.slice(0, 69).trimEnd()}…` : line;
}

/* ---------- statistics ---------- */

export function wilson(k, n, z = 1.96) {
  if (!n) return [0, 0];
  const p = k / n;
  const d = 1 + (z * z) / n;
  const c = p + (z * z) / (2 * n);
  const r = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [Math.max(0, (c - r) / d), Math.min(1, (c + r) / d)];
}

function logFact(n) {
  let s = 0;
  for (let i = 2; i <= n; i++) s += Math.log(i);
  return s;
}

/** Two-sided Fisher exact test on [[a, b], [c, d]]. */
export function fisher(a, b, c, d) {
  const n = a + b + c + d;
  const row1 = a + b;
  const col1 = a + c;
  const lf = (k) => logFact(row1) + logFact(n - row1) + logFact(col1) + logFact(n - col1) - logFact(n) - logFact(k) - logFact(row1 - k) - logFact(col1 - k) - logFact(n - row1 - col1 + k);
  const observed = lf(a);
  let p = 0;
  for (let k = Math.max(0, col1 - (n - row1)); k <= Math.min(row1, col1); k++) {
    const v = lf(k);
    if (v <= observed + 1e-9) p += Math.exp(v);
  }
  return Math.min(1, p);
}

/* ---------- bench ---------- */

export function cellOf(result) {
  if (result.passed) return { code: result.first_pass_passed === false ? "repaired" : "pass" };
  return { code: failureCode(result.failure_cause, result.status) };
}

export function buildBench(catalog = {}) {
  const batches = new Map((catalog.batches || []).map((b) => [b.batch_id, b]));
  const listed = new Set();
  const experiments = (catalog.experiments || []).map((e) => {
    const own = (e.batches || []).map((id) => batches.get(id)).filter(Boolean);
    own.forEach((b) => listed.add(b.batch_id));
    return { ...e, resolved: own };
  });
  const loose = [...batches.values()].filter((b) => !listed.has(b.batch_id));
  if (loose.length) {
    const byVariant = new Map();
    for (const b of loose) {
      const key = `${b.variant || "unlabelled"} · ${b.batch_id.slice(7, 15)}`;
      if (!byVariant.has(key)) byVariant.set(key, []);
      byVariant.get(key).push(b);
    }
    for (const [key, list] of byVariant) experiments.push({ id: `loose-${key}`, title: key, status: "done", loose: true, resolved: list });
  }
  for (const e of experiments) Object.assign(e, summarizeExperiment(e.resolved || []));
  const byId = new Map(experiments.map((e) => [e.id, e]));
  for (const e of experiments) {
    const ref = e.compare_to ? byId.get(e.compare_to) : null;
    if (ref && ref.n && e.n) e.comparison = { ref: ref.id, refTitle: ref.title, delta: e.k - ref.k, p: fisher(e.k, e.n - e.k, ref.k, ref.n - ref.k) };
  }
  return { question: catalog.question || "", model: catalog.model || "", experiments };
}

export function summarizeExperiment(batches) {
  const tasks = [];
  const levels = [];
  const results = [];
  batches.forEach((b, bi) => {
    for (const r of b.results || []) {
      if (!tasks.includes(r.task)) tasks.push(r.task);
      if (!levels.includes(r.reasoning_level)) levels.push(r.reasoning_level);
      results.push({ ...r, batch: bi, batch_id: b.batch_id, ...cellOf(r) });
    }
  });
  tasks.sort();
  const rank = (level) => (LEVELS.includes(level) ? LEVELS.indexOf(level) : LEVELS.length);
  levels.sort((a, b) => rank(a) - rank(b));
  const n = results.length;
  const k = results.filter((r) => r.passed).length;
  const rows = tasks.map((task) => {
    const cells = [];
    for (const level of levels) for (let bi = 0; bi < batches.length; bi++) {
      cells.push(results.find((r) => r.task === task && r.reasoning_level === level && r.batch === bi) || { code: "none", task, reasoning_level: level, batch: bi });
    }
    const mine = results.filter((r) => r.task === task);
    return { task, title: taskTitle(task), cells, k: mine.filter((r) => r.passed).length, n: mine.length };
  });
  const causes = {};
  for (const r of results) if (!r.passed) causes[r.code] = (causes[r.code] || 0) + 1;
  const repairs = results.filter((r) => r.repair_outcome);
  const mean = (key) => (n ? results.reduce((s, r) => s + (Number(r[key]) || 0), 0) / n : 0);
  return {
    tasks, levels, batchCount: batches.length, rows, results, n, k,
    firstPass: results.filter((r) => r.passed && r.first_pass_passed !== false).length,
    repaired: results.filter((r) => r.code === "repaired").length,
    repairEpisodes: { passed: repairs.filter((r) => r.repair_outcome === "passed").length, total: repairs.length },
    causes, ci: wilson(k, n), meanCalls: mean("model_calls"), meanSeconds: mean("elapsed_seconds"),
    model: batches[0]?.model || "",
  };
}
