import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

const uiDir = fileURLToPath(new URL("./", import.meta.url));
const tasksDir = fileURLToPath(new URL("../tasks/", import.meta.url));
const html = readFileSync(`${uiDir}index.html`, "utf8");
const app = readFileSync(`${uiDir}app.js`, "utf8");
const css = readFileSync(`${uiDir}styles.css`, "utf8");
let favicon = "";
try {
  favicon = readFileSync(`${uiDir}favicon.svg`, "utf8");
} catch (error) {
  favicon = "";
}

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
    assert.match(content, /finish/i);
  }
  const catalog = JSON.parse(readFileSync(`${tasksDir}catalog.json`, "utf8"));
  assert.deepEqual(Object.keys(catalog.tasks).sort(), expected.map(([name]) => name).sort());
  for (const entry of Object.values(catalog.tasks)) {
    assert.equal(typeof entry.description, "string");
    assert.ok(entry.gates);
    assert.equal(entry.gates.require_workflow_gates, true);
  }
});

test("run preset selection exposes its purpose before launch", () => {
  assert.match(html, /id="taskPresetDescription"/);
  assert.match(app, /function renderTaskPresetDescription\(/);
  assert.match(app, /task\?\.description/);
  assert.match(app, /renderTaskPresetDescription\(/);
});

test("runs preserve the selected task identity for comparison", () => {
  assert.match(html, /id="runPresetLabel"/);
  assert.match(app, /task_name:/);
  assert.match(app, /task_profile/);
  assert.match(app, /detailRow\("Task"/);
  assert.match(app, /runPresetLabel/);
});

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
   "workspaceDialog", "runDialog", "detailsBackdrop", "rightRail", "skillSummary",
    "skillOverride", "findSkillsButton", "skillSearch", "skillResults", "stopJobButton", "stopRunButton", "resumeRunButton",
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
  assert.match(app, /\/resume/);
 assert.match(app, /\/stop/);
  assert.match(app, /sessions.*\/stop|\/stop/);
  assert.match(app, /interrupted/);
  assert.match(css, /\.workflow-step\.active/);
  assert.match(css, /\.workflow-step\.blocked/);
  assert.match(css, /\.job-recovery/);
});

test("durable review evidence has a visible inspector surface", () => {
  assert.match(html, /data-details-tab="review"/);
  assert.match(html, /id="detailsReview"/);
  assert.match(html, /id="reviewDiff"/);
  assert.match(app, /function renderReview\(/);
  assert.match(app, /activeRecord\?\.review/);
  assert.match(app, /value\.status/);
  assert.match(css, /\.review-diff/);
});

test("tool approval controls expose durable confirm and resume actions", () => {
  for (const id of ["approvalMode", "approvalJob", "approveJobButton", "denyJobButton", "approveRunButton", "denyRunButton"]) {
    assert.match(html, new RegExp(`id="${id}"`), `missing #${id}`);
  }
  assert.match(app, /function changeApprovalMode\(/);
  assert.match(app, /function resolveJobApproval\(/);
  assert.match(app, /function resolveRunApproval\(/);
  assert.match(app, /sessions.*\/approval|\/approval/);
  assert.match(app, /approval_mode/);
  assert.match(app, /Workspace lease/);
  assert.match(app, /Tool receipt/);
  assert.match(css, /\.approval-control/);
  assert.match(css, /\.approval-job/);
});

test("provider controls keep remote API credentials behind an explicit connection flow", () => {
  for (const id of ["providerButton", "providerDialog", "providerType", "providerEndpoint", "providerModel", "providerApiKey", "saveProviderButton"]) {
    assert.match(html, new RegExp(`id="${id}"`), `missing #${id}`);
  }
  assert.match(app, /function saveProvider\(/);
  assert.match(app, /\/api\/provider/);
  assert.match(html, /never written to the project, transcript, or Git/);
  assert.match(css, /\.provider-fields/);
});

test("recovery events have readable activity copy", () => {
  assert.match(app, /case "recovery_retry"/);
  assert.match(app, /case "recovery_duplicate_action"/);
  assert.match(app, /case "recovery_exhausted"/);
  assert.match(app, /case "workflow_late_evidence"/);
  assert.match(app, /recovery_exhausted.*return "error"|return "error".*recovery_exhausted/s);
});

test("tool receipt lifecycle has readable activity copy", () => {
  for (const event of ["tool_call_started", "tool_call_completed", "tool_call_settled", "tool_result_replayed", "tool_outcome_unknown"]) {
    assert.match(app, new RegExp(`case "${event}"`), `missing ${event} copy`);
  }
  assert.match(app, /tool_receipt/);
});

test("context compaction and targeted edit actions remain visible to the UI contract", () => {
  assert.match(app, /context_compacted/);
  assert.match(app, /replace_text/);
  assert.match(app, /delete_file/);
});

test("skill controls expose recorded defaults, overrides, and discovery", () => {
  assert.match(html, /id="skillSummary"/);
  assert.match(html, /id="skillOverride"/);
  assert.match(html, /id="findSkillsButton"/);
  assert.match(html, /id="skillSearch"/);
  assert.match(html, /id="skillResults"/);
  assert.match(app, /\/api\/skills/);
  assert.match(app, /\/api\/skills\/discover/);
  assert.match(app, /skill_overrides/);
  assert.match(app, /function renderSkill/);
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
  assert.match(app, /function resumeRun\(/);
 assert.match(app, /function stopRun\(/);
  assert.match(app, /function stopJob\(/);
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

test("runs expose a live work surface without hiding the detailed ledger", () => {
  for (const id of ["runActivityPanel", "runActivityHeading", "runActivityState", "runActivityNow", "runActivityTimeline"]) {
    assert.match(html, new RegExp(`id="${id}"`), `missing #${id}`);
  }
  assert.match(html, /id="runActivityState"[^>]*role="status"/);
  assert.match(html, /id="runActivityTimeline"[^>]*aria-live="polite"/);
  assert.match(app, /function renderRunActivity\(/);
  assert.match(app, /renderRunActivity\(run\)/);
  assert.match(css, /\.run-activity-panel/);
  assert.match(css, /\.run-activity-timeline/);
});

test("run lifecycle checkpoints use human-readable vocabulary", () => {
  assert.match(app, /case "workspace_lock_acquired"/);
  assert.match(app, /case "workspace_lock_released"/);
  assert.match(app, /case "invalid_model_action"/);
});

test("run activity presents a narrative feed over the event ledger", () => {
  for (const id of ["runActivityFeed", "runActivityNowTitle", "runActivityNowCopy", "runActivityJump"]) {
    assert.match(html, new RegExp(`id="${id}"`), `missing #${id}`);
  }
  assert.match(html, /Summaries derived from recorded model, tool, and workflow events\./);
  assert.match(app, /function deriveActivityFeed\(/);
  assert.match(app, /deriveActivityFeed\(events\)/);
  assert.match(app, /runActivityJump/);
  assert.match(css, /\.run-activity-feed/);
  assert.match(css, /\.run-activity-item/);
  assert.match(css, /\.run-activity-tool/);
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

