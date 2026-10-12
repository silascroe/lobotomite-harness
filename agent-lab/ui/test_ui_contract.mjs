// Contract checks for the console: the capabilities the harness and the
// operator rely on stay present, the showcase stays read-only, and model text
// is escaped before it reaches the page.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { ShowcaseSource, ShowcaseError } from "./source.js";

const uiDir = fileURLToPath(new URL("./", import.meta.url));
const tasksDir = fileURLToPath(new URL("../tasks/", import.meta.url));
const read = (name) => readFileSync(`${uiDir}${name}`, "utf8");
const html = read("index.html");
const app = read("app.js");
const css = read("styles.css");
const source = read("source.js");
const specimen = read("specimen.js");

test("built-in run catalog contains focused gate-compatible presets", () => {
  const expected = [
    ["001-static-page.md", "Static page smoke test"],
    ["002-file-roundtrip.md", "File round-trip smoke test"],
    ["003-structured-validation.md", "Structured validation smoke test"],
    ["004-mini-project.md", "Mini project smoke test"],
  ];
  for (const [name, title] of expected) {
    const content = readFileSync(`${tasksDir}${name}`, "utf8");
    assert.match(content, new RegExp(`^# ${title}$`, "m"), `${name} title`);
    assert.match(content, /workflow_checkpoint/);
    assert.match(content, /git_diff/);
  }
  const catalog = JSON.parse(readFileSync(`${tasksDir}catalog.json`, "utf8"));
  assert.deepEqual(Object.keys(catalog.tasks).sort(), expected.map(([name]) => name).sort());
  for (const entry of Object.values(catalog.tasks)) assert.equal(entry.gates.require_workflow_gates, true);
});

test("the shell mounts runs, chats, details, dialogs and replay", () => {
  for (const id of [
    "modeRuns", "modeChats", "recordList", "listSearch", "workspaceButton", "providerButton", "newButton",
    "runView", "chamber", "runSpecimen", "nowTitle", "phases", "feed", "checks", "meter", "files", "quoteCard", "runApproval", "runActions",
    "chatView", "chatMessages", "composer", "chatInput", "sendButton", "stopJobButton", "jobBanner", "reasoningSelect", "approvalSelect",
    "replay", "replayButton", "scrub", "speed",
    "drawer", "runDialog", "presetSelect", "presetDescription", "taskText", "runGated", "runReasoning", "runApproval", "skillList",
    "workspaceDialog", "projectName", "folderPath", "providerDialog", "providerKeyInput", "toasts", "banner",
  ]) {
    assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  }
  for (const tab of ["overview", "files", "changes", "events", "output"]) assert.match(html, new RegExp(`data-tab="${tab}"`), `missing ${tab} tab`);
  assert.match(html, /<script type="module" src="app.js">/);
});

test("runs start with their task identity, gates and settings", () => {
  for (const field of ["task_text", "task_name", "gated", "reasoning_level", "approval_mode", "project_path", "skill_overrides"]) {
    assert.ok(app.includes(`${field}:`) || app.includes(`.${field} =`), `startRun payload is missing ${field}`);
  }
  assert.match(app, /state\.source\.startRun\(/);
  assert.match(app, /state\.source\.stopRun\(/);
  assert.match(app, /state\.source\.resumeRun\(/);
  assert.match(app, /state\.source\.resolveRunApproval\(/);
});

test("chats keep send, stop, retry, approvals and settings", () => {
  for (const call of ["sendMessage", "stopJob", "retryJob", "resolveJobApproval", "sessionSettings", "createSession", "createProject", "configureProvider", "discoverSkills"]) {
    assert.ok(app.includes(`state.source.${call}(`), `app never calls ${call}`);
  }
  assert.match(app, /confirm_remote: remote/);
  assert.match(app, /interrupted/);
});

test("the live source uses the documented endpoints", () => {
  for (const endpoint of ["/api/runs", "/events?offset=", "/stop", "/resume", "/approval", "/retry", "/settings", "/messages", "/api/skills/discover", "/api/provider", "/api/projects"]) {
    assert.ok(source.includes(endpoint), `missing ${endpoint}`);
  }
  assert.match(source, /"Content-Type": "application\/json"/, "POSTs must be JSON to pass the server's CSRF guard");
});

test("the showcase refuses every action that would change something", async () => {
  const showcase = new ShowcaseSource();
  assert.equal(showcase.readOnly, true);
  for (const method of ["startRun", "stopRun", "resumeRun", "resolveRunApproval", "createSession", "sendMessage", "stopJob", "retryJob", "resolveJobApproval", "sessionSettings", "createProject", "configureProvider", "discoverSkills"]) {
    await assert.rejects(showcase[method]({}), ShowcaseError, `${method} must be refused`);
  }
  assert.match(source, /!loopback\) return new ShowcaseSource\(\)/, "non-loopback hosts must never probe for a live API");
});

test("model and file text is escaped before it reaches the page", () => {
  assert.match(app, /const esc = \(value\) =>/);
  assert.match(app, /function partsHtml\(parts\)[\s\S]*?esc\(part\.v\)/);
  assert.match(app, /bubble[^`]*\$\{esc\(message\.content\)\}/);
  assert.match(app, /<pre class="preview">\$\{esc\(result\.content\)\}/);
  assert.doesNotMatch(app, /innerHTML\s*=\s*message\.content/);
});

test("the verdict leads and the model's own summary is marked unverified", () => {
  assert.match(html, /The model's own summary <small>unverified<\/small>/);
  assert.match(app, /Passed · repaired/);
  assert.match(app, /first_pass_passed/);
});

test("motion, layout and reasoning privacy guarantees hold", () => {
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(specimen, /prefers-reduced-motion: reduce/);
  assert.match(specimen, /visibilitychange/, "the specimen pauses in hidden tabs");
  assert.match(css, /@container main/);
  assert.match(app, /delete data\.reasoning_content/, "raw model reasoning stays out of the events pane");
});
