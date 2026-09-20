import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

const uiDir = fileURLToPath(new URL("./", import.meta.url));
const html = readFileSync(`${uiDir}index.html`, "utf8");
const app = readFileSync(`${uiDir}app.js`, "utf8");
const css = readFileSync(`${uiDir}styles.css`, "utf8");
let favicon = "";
try {
  favicon = readFileSync(`${uiDir}favicon.svg`, "utf8");
} catch (error) {
  favicon = "";
}

test("shell exposes separate Chats and Runs modes", () => {
  assert.match(html, /id="chatsModeButton"[^>]*aria-controls="chatNavigation chatSurface"/);
  assert.match(html, /id="runsModeButton"[^>]*aria-controls="runNavigation runSurface"/);
  assert.match(html, /id="chatNavigation"/);
  assert.match(html, /id="runNavigation"/);
  assert.match(html, /id="chatSurface"/);
  assert.match(html, /id="runSurface"/);
  assert.match(html, /id="runEmptyState"/);
  assert.match(html, /id="runOverview"/);
});

test("critical legacy capabilities remain mounted", () => {
  for (const id of [
    "projectSelect", "projectName", "workspacePath", "sessionSearch", "sessionList", "runList",
    "taskPreset", "taskText", "useGates", "reasoningLevel", "workflowSteps", "chatMessages",
    "chatInput", "retryJobButton", "activity", "fileList", "filePreview", "rawOutput",
    "workspaceDialog", "runDialog", "detailsBackdrop", "rightRail",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`), `missing #${id}`);
  }
  assert.doesNotMatch(html, /id="attachButton"/);
});

test("workflow and retry contracts remain intact", () => {
  assert.match(html, /id="workflowRail"/);
  assert.match(html, /id="workflowSummary"/);
  assert.match(html, /id="workflowNext"/);
  assert.match(app, /const WORKFLOW_PHASES/);
  assert.match(app, /function normalizeWorkflow/);
  assert.match(app, /function renderWorkflow/);
  assert.match(app, /function renderJobRecovery/);
  assert.match(app, /\/retry/);
  assert.match(app, /interrupted/);
  assert.match(css, /\.workflow-step\.active/);
  assert.match(css, /\.workflow-step\.blocked/);
  assert.match(css, /\.job-recovery/);
});

test("browser code owns mode, modal, and details presentation state", () => {
  assert.match(app, /mode:\s*["']chats["']/);
  assert.match(app, /detailsTab:\s*["']overview["']/);
  assert.match(app, /function setMode\(/);
  assert.match(app, /function openModal\(/);
  assert.match(app, /function closeModal\(/);
  assert.match(app, /function restoreModalFocus\(/);
  assert.match(app, /function setDetailsTab\(/);
  assert.match(app, /function renderRunSurface\(/);
  assert.match(app, /setMode\(["']runs["']/);
  assert.match(app, /setMode\(["']chats["']/);
});

test("styles define the approved visual and responsive system", () => {
  for (const token of ["#151713", "#252A22", "#EBE7D9", "#D38B62", "#91B8A5"]) {
    assert.match(css.toUpperCase(), new RegExp(token.toUpperCase()));
  }
  assert.match(css, /\.navigation-rail/);
  assert.match(css, /\.details-drawer/);
  assert.match(css, /dialog\[open\]/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.doesNotMatch(css, /text-transform:\s*uppercase/);
});

test("second-pass palette has a distinct workshop identity", () => {
  assert.match(css, /--copper:\s*#d38b62/i);
  assert.match(css, /--copper-strong:\s*#e4ad86/i);
  assert.match(css, /--mint:\s*#91b8a5/i);
  assert.doesNotMatch(css, /#10141c|#1a2130|#8d91f7|#65b8c7/i);
});

test("run failures render readable summaries", () => {
  assert.match(app, /function readableSummary\(/);
  assert.match(app, /error\?\.message/);
  assert.match(app, /readableSummary\(summary\.summary\)/);
});

test("project identity and run launch copy do not inherit stale record state", () => {
  assert.match(app, /topbar\.textContent = project\?\.name/);
  assert.match(app, /dialogId === ["']runDialog["'][\s\S]*launchNote/);
  assert.match(app, /Runs use the active project and reasoning level\./);
});

test("icon-only mobile controls retain accessible names", () => {
  assert.match(html, /id="inspectorToggle"[^>]*aria-label="Details"/);
  assert.match(html, /id="sidebarToggle"[^>]*aria-label="Open navigation"/);
});

test("selecting historical records preserves the active project context", () => {
  const runRenderer = app.match(/function renderRun\(run\)[\s\S]*?(?=function renderSession)/)?.[0] || "";
  const sessionRenderer = app.match(/function renderSession\(session\)[\s\S]*?(?=async function selectRun)/)?.[0] || "";
  assert.doesNotMatch(runRenderer, /workspacePath/);
  assert.doesNotMatch(sessionRenderer, /workspacePath/);
  assert.match(app, /function workspaceLabelForRecord\(/);
  assert.match(sessionRenderer, /composerWorkspace/);
});

test("cold boot stays blank until the user chooses a conversation", () => {
  const loader = app.match(/async function loadSessions\(\)[\s\S]*?(?=async function createSession)/)?.[0] || "";
  assert.doesNotMatch(loader, /await selectSession\(/);
  assert.doesNotMatch(loader, /await createSession\(/);
  assert.match(app, /if \(!state\.activeSession\) await createSession\(\);/);
});

test("brand favicon is wired as a sharp project asset", () => {
  assert.match(html, /<link rel="icon" type="image\/svg\+xml" href="favicon\.svg\?v=[^"]+">/);
  assert.match(favicon, /<svg[^>]*viewBox="0 0 64 64"/);
  assert.match(favicon, /#d38b62/i);
  assert.match(favicon, /#91b8a5/i);
  assert.match(favicon, /<title(?:\s+id="[^"]+")?>Agent Lab<\/title>/);
});

test("closed off-canvas regions are removed from keyboard navigation", () => {
  assert.match(html, /id="rightRail"[^>]*\sinert/);
  assert.match(app, /rightRail["']\)\.toggleAttribute\(["']inert["'], !open\)/);
  assert.match(app, /function syncResponsiveInert\(/);
  assert.match(app, /sidebar["']\)\.toggleAttribute\(["']inert["'], mobile/);
});
