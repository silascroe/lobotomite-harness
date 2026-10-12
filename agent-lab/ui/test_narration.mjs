import assert from "node:assert/strict";
import test from "node:test";
import { buildRunModel, buildChatActivity, partsText, chatTitle, runTitle, clockText } from "./narration.js";

let clock = Date.parse("2026-10-11T12:00:00Z");
const at = (seconds = 1) => new Date((clock += seconds * 1000)).toISOString();
const ev = (event, data = {}, seconds = 1) => ({ event, timestamp: at(seconds), data });
const started = (action, summary = {}) => ev("tool_call_started", { receipt: { action, summary: { action, ...summary } } });
const result = (action, args, res, turn) => ev("tool_result", { turn, action, args, result: res });

test("a tool call reads in the present tense, then the past tense", () => {
  const events = [ev("run_created", { mode: "managed" }), ev("model_response", { turn: 1 }), started("write_file", { path: "index.html" })];
  let model = buildRunModel(events, { status: "running" });
  const row = model.rows.at(-1);
  assert.equal(row.state, "active");
  assert.equal(partsText(row.parts), "Writing index.html");
  assert.equal(model.now.mode, "tool");
  assert.equal(partsText(model.now.title), "Writing index.html");

  events.push(result("write_file", { path: "index.html", content: "<main></main>" }, { ok: true, path: "index.html", bytes: 2048 }, 1));
  model = buildRunModel(events, { status: "running" });
  assert.equal(model.rows.length, 2, "the result updates the started row instead of adding one");
  assert.equal(partsText(model.rows.at(-1).parts), "Wrote index.html · 2.0 KB");
  assert.equal(model.rows.at(-1).state, "ok");
  assert.equal(model.files.get("index.html"), 2048);
  assert.equal(model.now.mode, "think", "after a tool returns the model is thinking about its next turn");
  assert.equal(model.now.sub, "Working out turn 2");
});

test("failures carry their error and listing counts real entries", () => {
  const model = buildRunModel([
    ev("model_response", { turn: 1 }),
    result("list_files", { path: "." }, { ok: true, entries: [{ path: "a" }, { path: "b" }] }, 1),
    ev("model_response", { turn: 2 }),
    result("run_command", { command: "node app.js" }, { ok: true, exit_code: 1, stderr: "SyntaxError: nope" }, 2),
    ev("model_response", { turn: 3 }),
    result("apply_patch", { patch: "x" }, { ok: false, error: "could not find update-patch context" }, 3),
  ], { status: "running" });
  assert.equal(partsText(model.rows[0].parts), "Looked around · 2 items");
  assert.equal(model.rows[1].state, "bad");
  assert.match(model.rows[1].detail, /SyntaxError/);
  assert.equal(model.rows[2].state, "bad");
  assert.match(model.rows[2].detail, /update-patch context/);
  assert.equal(model.calls, 3);
  assert.equal(model.tools, 3);
});

test("evaluator reports become check grids and failing headlines", () => {
  const failing = { passed: false, stdout: JSON.stringify({ checks: { focus_style: false, links_css: true } }), findings: [{ id: "focus_style", message: "Add a focus style." }] };
  const passing = { passed: true, stdout: JSON.stringify({ checks: { focus_style: true, links_css: true } }), findings: [] };
  const events = [
    ev("model_response", { turn: 9 }),
    ev("finish_rejected", { reason: "The external evaluator rejected the project. ..." }),
    ev("evaluator", { result: failing }),
  ];
  let model = buildRunModel(events, { status: "running" });
  assert.equal(model.rows.filter((r) => r.kind === "eval").length, 1);
  assert.equal(model.rows.some((r) => partsText(r.parts) === "Asked to finish, sent back"), false, "evaluator rejections are not duplicated");
  assert.deepEqual(model.checks, { focus_style: false, links_css: true });
  assert.equal(partsText(model.now.title), "1 check failing");
  assert.equal(model.now.sub, "focus_style");
  assert.equal(model.rows.at(-1).eval.findings[0].id, "focus_style");

  events.push(ev("evaluator", { result: passing }), ev("finish", { status: "success", summary: "All done, trust me." }));
  model = buildRunModel(events, { status: "success", firstPassPassed: false });
  assert.deepEqual(model.previousChecks, { focus_style: false, links_css: true });
  assert.equal(model.finished, true);
  assert.equal(partsText(model.now.title), "Passed after repair");
  assert.equal(model.finish.summary, "All done, trust me.");
  assert.equal(model.phase, "complete");
});

test("plain finish refusals, compaction and phase changes read cleanly", () => {
  const model = buildRunModel([
    ev("model_response", { turn: 1 }),
    started("write_file", { path: "a.txt" }),
    ev("workflow_phase", { source: "automatic", state: { phase: "implement" } }),
    result("write_file", { path: "a.txt" }, { ok: true, path: "a.txt", bytes: 3 }, 1),
    ev("context_compacted", { dropped_messages: 4 }),
    ev("context_compacted", { dropped_messages: 9 }),
    ev("finish_rejected", { reason: "success is not accepted yet; workflow evidence missing: plan" }),
  ], { status: "running" });
  const write = model.rows.find((r) => partsText(r.parts).startsWith("Wrote"));
  assert.equal(write.phaseTag, "implement", "the row that caused the phase change carries the tag");
  const context = model.rows.filter((r) => r.icon === "fold");
  assert.equal(context.length, 1, "repeated compaction folds into one row");
  assert.match(partsText(context[0].parts), /9 messages/);
  assert.equal(model.rows.at(-1).detail, "workflow evidence missing: plan");
  assert.equal(partsText(model.now.title), "Sent back to the bench");
});

test("terminal states without a finish event use the recorded reason", () => {
  const model = buildRunModel([
    ev("model_response", { turn: 1 }),
    ev("recovery_exhausted", { decision: { detail: "apply_patch: could not find update-patch context" } }),
  ], { status: "blocked" });
  assert.equal(model.finished, true);
  assert.equal(model.now.mode, "fail");
  assert.match(model.now.sub, /update-patch context/);
});

test("approval waits and interruptions are explicit", () => {
  const waiting = buildRunModel([ev("approval_requested", { action: "write_file" })], { status: "waiting_approval" });
  assert.equal(partsText(waiting.now.title), "Waiting for your approval");
  const paused = buildRunModel([ev("model_response", { turn: 1 })], { status: "interrupted" });
  assert.equal(partsText(paused.now.title), "Interrupted");
});

test("chat work is grouped under the reply it produced", () => {
  const activity = buildChatActivity([
    ev("model_response", { step: 1 }),
    started("read_file", { path: "README.md" }),
    ev("tool_result", { step: 1, action: "read_file", args: { path: "README.md" }, result: { ok: true } }),
    ev("assistant_message", { content: "It is a README." }),
    ev("model_response", { step: 1 }),
    started("list_files", { path: "." }),
  ]);
  assert.equal(activity.groups.length, 1);
  assert.equal(partsText(activity.groups[0].rows[0].parts), "Read README.md");
  assert.equal(activity.live.rows.length, 1);
  assert.equal(activity.live.rows[0].state, "active");
});

test("titles come from content, not ids", () => {
  assert.equal(chatTitle([{ role: "user", content: "Build me a field notebook\nwith cards" }]), "Build me a field notebook");
  assert.equal(chatTitle([], "Empty"), "Empty");
  assert.equal(runTitle({ task_profile: { title: "Static page smoke test" } }), "Static page");
  assert.equal(clockText(125), "2:05");
});
