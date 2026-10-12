// Turns the harness event log into what the console shows: activity rows, the
// current headline, workflow phase, budget, evaluator checks and files.
// Pure functions with no DOM access, so the live view, replay, chats and the
// showcase all render through the same logic, and Node tests can import it.
// Rows carry structured text parts; the renderer escapes them.

export const PHASES = ["inspect", "plan", "implement", "verify", "review", "complete"];

const text = (v) => ({ t: "text", v: String(v ?? "") });
const code = (v) => ({ t: "code", v: String(v ?? "") });
const dim = (v) => ({ t: "dim", v: String(v ?? "") });

export function formatBytes(n) {
  if (n == null || Number.isNaN(Number(n))) return "";
  const value = Number(n);
  return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KB`;
}

export function clockText(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function joinCode(list) {
  const parts = [];
  list.forEach((item, index) => {
    if (index) parts.push(text(", "));
    parts.push(code(item));
  });
  return parts;
}

// Present tense while a tool runs, past tense once it returns.
export const VERBS = {
  list_files: {
    icon: "look",
    now: () => [text("Looking around the project")],
    done: (a, r) => {
      const count = Array.isArray(r.entries) ? r.entries.length : Number(r.entries) || 0;
      return count ? [text("Looked around"), dim(` · ${count} item${count === 1 ? "" : "s"}`)] : [text("Looked around"), dim(" · empty project")];
    },
  },
  read_file: { icon: "read", now: (a) => [text("Reading "), code(a.path)], done: (a) => [text("Read "), code(a.path)] },
  write_file: {
    icon: "write",
    now: (a) => [text("Writing "), code(a.path)],
    done: (a, r) => [text("Wrote "), code(r.path || a.path), ...(r.bytes != null ? [dim(` · ${formatBytes(r.bytes)}`)] : [])],
  },
  replace_text: { icon: "write", now: (a) => [text("Editing "), code(a.path)], done: (a, r) => [text("Edited "), code(r.path || a.path)] },
  apply_patch: {
    icon: "write",
    now: () => [text("Patching files")],
    done: (a, r) => (Array.isArray(r.changed) && r.changed.length ? [text("Patched "), ...joinCode(r.changed)] : [text("Patched files")]),
  },
  delete_file: { icon: "x", now: (a) => [text("Removing "), code(a.path)], done: (a) => [text("Removed "), code(a.path), dim(" · backup kept")] },
  run_command: {
    icon: "run",
    now: (a) => [text("Running "), code(a.command)],
    done: (a, r) => [text("Ran "), code(a.command || r.command), dim(` · exit ${r.exit_code ?? (r.timed_out ? "timeout" : "?")}`)],
  },
  git_diff: { icon: "diff", now: () => [text("Reviewing the diff")], done: () => [text("Reviewed the full diff")] },
  workflow_checkpoint: {
    icon: "flag",
    now: (a) => [text(`Noting a ${a.phase || "workflow"} checkpoint`)],
    done: (a) => [text(`Noted a ${a.phase || "workflow"} checkpoint`)],
  },
  find_skills: { icon: "look", now: () => [text("Searching the skill shelf")], done: () => [text("Searched the skill shelf")] },
};

function verbFor(action) {
  return VERBS[action] || {
    icon: "dot",
    now: () => [text(`Using ${String(action || "a tool").replace(/_/g, " ")}`)],
    done: () => [text(`Used ${String(action || "a tool").replace(/_/g, " ")}`)],
  };
}

export function partsText(parts) {
  return (parts || []).map((part) => part.v).join("");
}

function toolFailed(action, result) {
  return result?.ok === false || Boolean(result?.error) || (action === "run_command" && Boolean(result?.exit_code));
}

function failureDetail(result) {
  return String(result?.error || result?.stderr || "The tool reported a failure.").trim().slice(0, 420);
}

function stripAcceptance(reason) {
  return String(reason || "").replace(/^success is not accepted yet;\s*/, "");
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

const TERMINAL = new Set(["success", "complete", "blocked", "error", "failed", "aborted"]);

/**
 * Build the run view model from ordered events.
 * options.status: the run's current status ("running", "success", ...). Replay
 * passes "running" until its final event so a partial log reads as live.
 */
export function buildRunModel(events, options = {}) {
  const list = Array.isArray(events) ? events.filter((e) => e && e.event) : [];
  const status = options.status || "running";
  const model = {
    rows: [],
    phase: "intake",
    turn: 0,
    calls: 0,
    tools: 0,
    evalCount: 0,
    checks: null,
    previousChecks: null,
    files: new Map(),
    startTs: list.length ? Date.parse(list[0].timestamp) : null,
    lastTs: list.length ? Date.parse(list[list.length - 1].timestamp) : null,
    finish: null,
    repair: null,
    blockedReason: "",
    now: null,
  };
  const rel = (ev) => (model.startTs == null ? 0 : (Date.parse(ev.timestamp) - model.startTs) / 1000);
  let active = null;
  let lastRow = null;
  let contextRow = null;
  let lastSignal = null; // what the headline should describe

  const add = (row) => {
    const full = { key: `r${model.rows.length}`, state: "ok", icon: "dot", parts: [], detail: "", turn: model.turn, at: 0, ...row };
    model.rows.push(full);
    lastRow = full;
    return full;
  };

  list.forEach((ev, index) => {
    const d = ev.data || {};
    const at = rel(ev);
    switch (ev.event) {
      case "run_created":
        add({ key: `e${index}`, state: "note", icon: "dot", parts: [text(d.mode === "selected" ? "Attached to the selected project" : "Opened a fresh project workspace")], turn: 0, at });
        lastSignal = { kind: "start" };
        break;
      case "model_response":
        model.calls += 1;
        model.turn = Number(d.turn ?? d.step ?? model.turn + 1) || model.turn + 1;
        lastSignal = { kind: "decided" };
        break;
      case "tool_call_started": {
        const action = d.receipt?.action;
        const summary = d.receipt?.summary || {};
        const args = { path: summary.path, command: summary.command, phase: summary.phase };
        active = add({ key: `e${index}`, state: "active", icon: verbFor(action).icon, parts: verbFor(action).now(args), action, at });
        lastSignal = { kind: "tool", row: active };
        break;
      }
      case "tool_result": {
        model.tools += 1;
        const action = d.action;
        const result = d.result || {};
        const args = d.args || {};
        const failed = toolFailed(action, result);
        const row = active && active.action === action ? active : add({ key: `e${index}`, action, at });
        row.state = failed ? "bad" : "ok";
        row.icon = failed ? "x" : verbFor(action).icon;
        row.parts = verbFor(action).done(args, result);
        row.detail = failed ? failureDetail(result) : "";
        active = null;
        lastRow = row;
        if (!failed && (action === "write_file" || action === "replace_text") && (result.path || args.path)) {
          model.files.set(result.path || args.path, result.bytes ?? model.files.get(result.path || args.path) ?? null);
        }
        if (!failed && action === "apply_patch") for (const p of result.changed || []) model.files.set(p, model.files.get(p) ?? null);
        if (!failed && action === "delete_file" && args.path) model.files.delete(args.path);
        lastSignal = { kind: failed ? "tool_failed" : "tool_done", row };
        break;
      }
      case "workflow_phase": {
        const phase = d.state?.phase;
        if (phase && phase !== model.phase) {
          model.phase = phase;
          if (PHASES.includes(phase) && phase !== "complete" && lastRow && d.source === "automatic" && !lastRow.phaseTag) lastRow.phaseTag = phase;
        }
        break;
      }
      case "workflow_late_evidence":
        add({ key: `e${index}`, state: "note", icon: "flag", parts: [text("Plan noted after the work was done "), dim("(kept as a note)")], at });
        break;
      case "finish_rejected": {
        const reason = String(d.reason || "");
        if (reason.startsWith("The external evaluator")) break; // the evaluator row tells this story
        add({ key: `e${index}`, state: "warn", icon: "flag", parts: [text("Asked to finish, sent back")], detail: stripAcceptance(reason), at });
        lastSignal = { kind: "rejected", reason: stripAcceptance(reason) };
        break;
      }
      case "evaluator": {
        const result = d.result || {};
        const checks = parseChecks(result);
        model.evalCount += 1;
        if (checks) {
          model.previousChecks = model.checks;
          model.checks = checks;
        }
        const entries = checks ? Object.entries(checks) : [];
        add({
          key: `e${index}`,
          kind: "eval",
          state: result.passed ? "ok" : "bad",
          icon: result.passed ? "check" : "x",
          parts: [text(result.error ? "The evaluator could not grade the project" : result.passed ? "Evaluator passed" : "Evaluator rejected")],
          eval: {
            index: model.evalCount,
            passed: Boolean(result.passed),
            passedCount: entries.filter(([, ok]) => ok).length,
            total: entries.length,
            findings: (result.findings || []).map((f) => ({ id: String(f.id || ""), message: String(f.message || "") })),
            error: result.error ? String(result.error) : "",
          },
          at,
        });
        lastSignal = { kind: "eval", passed: Boolean(result.passed), failing: entries.filter(([, ok]) => !ok).map(([k]) => k), total: entries.length };
        break;
      }
      case "repair_episode_started": {
        const rep = d.repair_episode || {};
        model.repair = rep;
        const count = (rep.initial_finding_ids || []).length;
        add({ key: `e${index}`, state: "warn", icon: "loop", parts: [text("Repair opened")], detail: `${count} finding${count === 1 ? "" : "s"} to fix · up to ${rep.extension_limit ?? 6} extra calls beyond the budget`, at });
        break;
      }
      case "repair_rechecked":
        model.repair = d.repair_episode || model.repair;
        break;
      case "repair_episode_finished": {
        const rep = d.repair_episode || {};
        model.repair = rep;
        const ok = rep.status === "passed";
        add({
          key: `e${index}`,
          state: ok ? "ok" : "bad",
          icon: ok ? "check" : "x",
          parts: [text(ok ? "Repair succeeded" : `Repair stopped · ${String(rep.status || "").replace(/_/g, " ")}`)],
          detail: `${rep.repair_episode_turns ?? "?"} turns in the episode · ${rep.extension_turns_used ?? 0} extra calls used`,
          at,
        });
        break;
      }
      case "context_compacted": {
        const parts = [text("Condensing older context"), dim(` · ${d.dropped_messages ?? 0} messages folded so far`)];
        if (contextRow) contextRow.parts = parts;
        else contextRow = add({ key: `e${index}`, state: "note", icon: "fold", parts, at });
        break;
      }
      case "invalid_model_action":
        add({ key: `e${index}`, state: "warn", icon: "loop", parts: [text("The model's reply needed repair")], detail: String(d.error || "").slice(0, 240), at });
        lastSignal = { kind: "slip" };
        break;
      case "recovery_retry":
        if (["finish_rejected", "tool_failure", "invalid_model_action"].includes(d.decision?.category)) break; // already shown
        add({ key: `e${index}`, state: "warn", icon: "loop", parts: [text("Recovering from a protocol slip")], detail: String(d.decision?.detail || ""), at });
        break;
      case "recovery_duplicate_action":
        add({ key: `e${index}`, state: "warn", icon: "loop", parts: [text("Blocked a repeated action")], detail: String(d.decision?.detail || ""), at });
        break;
      case "recovery_exhausted":
        model.blockedReason = `Recovery exhausted: ${d.decision?.detail || ""}`;
        add({ key: `e${index}`, state: "bad", icon: "x", parts: [text("Recovery exhausted")], detail: String(d.decision?.detail || ""), at });
        break;
      case "approval_requested":
        add({ key: `e${index}`, state: "warn", icon: "hand", parts: [text("Waiting for your approval")], detail: String(d.summary?.action || d.action || ""), at });
        lastSignal = { kind: "approval" };
        break;
      case "approval_resolved":
        add({ key: `e${index}`, state: d.status === "approved" ? "ok" : "bad", icon: "hand", parts: [text(d.status === "approved" ? "Approved by you" : "Denied by you")], at });
        break;
      case "tool_result_replayed":
        add({ key: `e${index}`, state: "note", icon: "loop", parts: [text("Reused a recorded tool result after a restart")], at });
        break;
      case "tool_outcome_unknown":
        add({ key: `e${index}`, state: "warn", icon: "loop", parts: [text("A tool's outcome was unknown after a restart")], at });
        break;
      case "run_resumed":
      case "run_resumed_for_approval":
      case "run_resumed_from_tool_receipt":
        add({ key: `e${index}`, state: "note", icon: "loop", parts: [text("Resumed from the last checkpoint")], at });
        break;
      case "turn_limit":
        model.blockedReason = `Reached the ${d.max_turns ?? ""}-turn limit without finishing`;
        add({ key: `e${index}`, state: "bad", icon: "x", parts: [text("Reached the turn limit")], at });
        break;
      case "harness_error":
        model.blockedReason = String(d.error || "The harness reported an error");
        add({ key: `e${index}`, state: "bad", icon: "x", parts: [text("The harness hit an error")], detail: String(d.error || "").slice(0, 420), at });
        break;
      case "finish":
        model.finish = { status: d.status, summary: String(d.summary || "") };
        model.phase = d.status === "success" ? "complete" : model.phase;
        break;
      default:
        break;
    }
  });

  const finished = TERMINAL.has(status) || Boolean(model.finish);
  model.finished = finished;
  model.status = status;
  model.now = headline(model, status, lastSignal, options);
  return model;
}

function headline(model, status, signal, options) {
  if (model.finished) {
    const passed = status === "success" || status === "complete" || model.finish?.status === "success";
    const repaired = passed && options.firstPassPassed === false;
    if (passed) {
      return {
        mode: "pass",
        title: [text(repaired ? "Passed after repair" : model.evalCount ? "Passed on the first try" : "Finished")],
        sub: repaired
          ? `First evaluation failed; fixed in ${Math.max(1, model.evalCount - 1)} repair round${model.evalCount - 1 === 1 ? "" : "s"}.`
          : model.evalCount ? "Every check passed on the first evaluation." : "The run finished without an external evaluator.",
        tone: "",
        shimmer: false,
      };
    }
    const reason = options.blockedReason || model.blockedReason || model.finish?.summary || "The run stopped before it could finish.";
    return { mode: "fail", title: [text(status === "error" ? "Stopped by an error" : "Blocked")], sub: reason, tone: "bad", shimmer: false };
  }
  if (status === "waiting_approval" || signal?.kind === "approval") {
    return { mode: "wait", title: [text("Waiting for your approval")], sub: "The next project change is paused until you decide.", tone: "warn", shimmer: false };
  }
  if (status === "interrupted") {
    return { mode: "wait", title: [text("Interrupted")], sub: "Resume to continue from the last checkpoint.", tone: "warn", shimmer: false };
  }
  if (signal?.kind === "tool" && signal.row?.state === "active") {
    return { mode: "tool", title: signal.row.parts, sub: "Tool call in progress", tone: "", shimmer: true };
  }
  if (signal?.kind === "eval") {
    return signal.passed
      ? { mode: "pass", title: [text("All checks pass")], sub: `${signal.total} of ${signal.total} evaluator checks`, tone: "", shimmer: false }
      : { mode: "wait", title: [text(`${signal.failing.length} check${signal.failing.length === 1 ? "" : "s"} failing`)], sub: signal.failing.join(", "), tone: "bad", shimmer: false };
  }
  if (signal?.kind === "rejected") {
    return { mode: "wait", title: [text("Sent back to the bench")], sub: signal.reason, tone: "warn", shimmer: false };
  }
  if (signal?.kind === "start" || !signal) {
    return { mode: "think", title: [text("Waking the specimen")], sub: "Opening a fresh project workspace.", tone: "", shimmer: true };
  }
  return { mode: "think", title: [text("Thinking")], sub: `Working out turn ${model.turn + 1}`, tone: "", shimmer: true };
}

/**
 * Chat narration: group tool activity between assistant replies.
 * Returns { groups, live } where groups[i] is the work that preceded the i-th
 * assistant_message event, aligned from the end so a truncated event window
 * still pairs the newest replies with their work.
 */
export function buildChatActivity(events) {
  const list = Array.isArray(events) ? events.filter((e) => e && e.event) : [];
  const groups = [];
  let current = { rows: [], start: null, calls: 0 };
  let active = null;
  for (const ev of list) {
    const d = ev.data || {};
    const ts = Date.parse(ev.timestamp);
    switch (ev.event) {
      case "model_response":
        if (current.start == null) current.start = ts;
        current.calls += 1;
        break;
      case "tool_call_started": {
        const action = d.receipt?.action;
        const summary = d.receipt?.summary || {};
        if (current.start == null) current.start = ts;
        active = { state: "active", icon: verbFor(action).icon, parts: verbFor(action).now({ path: summary.path, command: summary.command, phase: summary.phase }), action, detail: "" };
        current.rows.push(active);
        break;
      }
      case "tool_result": {
        const action = d.action;
        const result = d.result || {};
        const failed = toolFailed(action, result);
        const row = active && active.action === action ? active : { action };
        row.state = failed ? "bad" : "ok";
        row.icon = failed ? "x" : verbFor(action).icon;
        row.parts = verbFor(action).done(d.args || {}, result);
        row.detail = failed ? failureDetail(result) : "";
        if (row !== active) current.rows.push(row);
        active = null;
        break;
      }
      case "invalid_model_action":
        current.rows.push({ state: "warn", icon: "loop", parts: [text("The model's reply needed repair")], detail: String(d.error || "").slice(0, 200) });
        break;
      case "approval_requested":
        current.rows.push({ state: "warn", icon: "hand", parts: [text("Waiting for your approval")], detail: "" });
        break;
      case "assistant_message":
        groups.push({ ...current, end: ts, seconds: current.start == null ? 0 : (ts - current.start) / 1000 });
        current = { rows: [], start: null, calls: 0 };
        active = null;
        break;
      default:
        break;
    }
  }
  return { groups, live: current };
}

export function chatTitle(conversation, fallback = "New conversation") {
  const first = (conversation || []).find((m) => m.role === "user" && String(m.content || "").trim());
  if (!first) return fallback;
  const line = String(first.content).trim().split(/\r?\n/)[0];
  return line.length > 64 ? `${line.slice(0, 61).trimEnd()}…` : line;
}

export function runTitle(run) {
  const title = run?.task_profile?.title || run?.title || "";
  if (title) return title.replace(/ smoke test$/i, "");
  return "Custom task";
}
