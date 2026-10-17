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
const views = read("views.js");
const recorder = read("recorder.js");
const css = read("styles.css");
const source = read("source.js");
const server = read("server.py");

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

test("the shell mounts navigation, dialogs and both layouts", () => {
  for (const id of [
    "view", "showcaseStrip", "providerButton", "workspaceButton", "newRunButton", "newChatButton", "newButton", "toasts",
    "runDialog", "presetSelect", "presetDescription", "taskText", "runGated", "runReasoning", "runApproval", "skillList", "skillQuery", "startRunButton",
    "workspaceDialog", "workspaceOptions", "projectName", "folderPath", "providerDialog", "providerKeyInput", "saveProviderButton",
  ]) assert.ok(html.includes(`id="${id}"`), `missing #${id}`);
  for (const route of ["#/bench", "#/runs", "#/chats"]) assert.ok(html.includes(`href="${route}"`), `missing nav to ${route}`);
  assert.match(html, /class="bottom-nav"/, "phones get a bottom tab bar");
  assert.match(html, /<script type="module" src="app.js">/);
  for (const file of ["app.js", "model.js", "views.js", "recorder.js", "source.js", "styles.css", "favicon.svg"]) assert.ok(server.includes(`"${file}"`), `server must serve ${file}`);
  for (const [, file] of css.matchAll(/url\("(fonts\/[^"]+)"\)/g)) {
    assert.ok(server.includes(`"${file.replace(/^fonts\//, "").replace(/\.woff2$/, "")}"`), `server must serve ${file}`);
    assert.ok(readFileSync(`${uiDir}${file}`).length > 1000, `${file} is bundled`);
  }
  assert.doesNotMatch(html, /fonts\.googleapis/, "no third-party font requests");
});

test("every run view and the replay transport exist", () => {
  for (const tab of ["recorder", "process", "files", "checks", "log"]) assert.ok(views.includes(`["${tab}",`), `missing ${tab} tab`);
  for (const id of ["scrub", "speed", "chatInput", "sendButton", "reasoningSelect", "approvalSelect", "runSearch"]) assert.ok(views.includes(`id="${id}"`), `missing #${id}`);
  assert.match(views, /data-act="play"/);
  assert.match(recorder, /class="tape-h"/, "desktop recorder runs left to right");
  assert.match(recorder, /class="tape-v"/, "phone recorder runs top to bottom");
  assert.match(recorder, /score-v/, "the file lens transposes on phones");
});

test("runs start with their task identity, gates and settings", () => {
  for (const field of ["task_text", "task_name", "gated", "reasoning_level", "approval_mode", "project_path", "skill_overrides"]) {
    assert.ok(app.includes(`${field}:`) || app.includes(`.${field} =`), `startRun payload is missing ${field}`);
  }
  for (const call of ["startRun", "stopRun", "resumeRun", "resolveRunApproval"]) assert.ok(app.includes(`state.source.${call}(`), `app never calls ${call}`);
});

test("chats keep send, stop, retry, approvals and settings", () => {
  for (const call of ["sendMessage", "stopJob", "retryJob", "resolveJobApproval", "sessionSettings", "createSession", "createProject", "configureProvider", "discoverSkills", "benchmarks"]) {
    assert.ok(app.includes(`state.source.${call}(`), `app never calls ${call}`);
  }
  assert.match(app, /confirm_remote: remote/);
  assert.match(views, /interrupted/);
});

test("the live source uses the documented endpoints", () => {
  for (const endpoint of ["/api/runs", "/api/benchmarks", "/events?offset=", "/stop", "/resume", "/approval", "/retry", "/settings", "/messages", "/api/skills/discover", "/api/provider", "/api/projects"]) {
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
  for (const [name, body] of [["views.js", views], ["recorder.js", recorder]]) {
    assert.match(body, /import \{[^}]*\besc\b/, `${name} must use esc()`);
    assert.doesNotMatch(body, /\$\{(m|message)\.content\}/, `${name} interpolates message content raw`);
    assert.doesNotMatch(body, /\$\{(t\.error|r\.content|a\.content|a\.patch|a\.command)\}/, `${name} interpolates tool output raw`);
  }
  assert.match(views, /msg user">\$\{esc\(m\.content\)\}/);
  assert.match(views, /\$\{esc\(m\.content\)\}<\/div>/);
  assert.doesNotMatch(app, /innerHTML\s*=\s*[^;]*\.content/);
});

test("the verdict leads, repairs are named, and the model's summary is marked unverified", () => {
  assert.match(views, /The model's own summary <small>unverified<\/small>/);
  assert.match(read("model.js"), /Passed · repaired/);
  assert.match(read("model.js"), /first_pass_passed/);
  assert.match(read("model.js"), /an external evaluator; nothing checked the result/, "ungraded success is not called a pass");
});

test("motion, phone layout and reasoning privacy guarantees hold", () => {
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /env\(safe-area-inset-bottom\)/, "the bottom bar clears the phone's home indicator");
  assert.match(views, /delete data\.reasoning_content/, "raw model reasoning stays out of the log");
  assert.match(html, /viewport-fit=cover/);
});
