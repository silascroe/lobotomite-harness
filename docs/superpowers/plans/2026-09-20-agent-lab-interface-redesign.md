# Agent Lab Interface Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Agent Lab's congested permanent three-column dashboard with a Codex-structured, visually original workbench that keeps Chats and Runs separate while preserving all current harness behavior.

**Architecture:** Keep the Python server, endpoints, records, and polling model unchanged. Rewrite the static HTML shell and CSS, then adapt the existing browser-side renderer with explicit `chats` and `runs` presentation modes, two native dialogs, and one optional details drawer. Existing element IDs and API functions remain the integration boundary wherever practical.

**Tech Stack:** Plain HTML, CSS, browser JavaScript, Node source-contract tests, Python `unittest`, existing local HTTP server.

**Spec:** `docs/superpowers/specs/2026-09-20-agent-lab-interface-redesign-design.md`

## Global Constraints

- Do not modify `agent-lab/ui/server.py`, the harness, endpoint payloads, persistence formats, model behavior, bridges, tunnel configuration, or deployment.
- Do not add a framework, package dependency, build tool, remote font, remote image, or UI library.
- Chats and Runs remain separate browser presentation modes backed by the existing session and run APIs.
- Preserve managed projects, scratch work, existing folders, search, reasoning, run presets, completion gates, workflow, retry, activity, artifacts, file preview, and raw output.
- Use sentence case; reserve monospace for paths, IDs, token counts, and raw output.
- Use the approved palette exactly: `#10141C`, `#1A2130`, `#EAECF1`, `#969EAE`, `#8D91F7`, `#65B8C7`, with `#D6A75F` for warnings and `#E07A82` for failures.
- Desktop uses a quiet navigation rail and dominant work surface; Details is never a permanent third column.
- Narrow layouts use drawers/sheets without horizontal document overflow.
- Respect keyboard focus, semantic labels, dialog focus behavior, live status, and reduced motion.
- The workspace root is not a Git repository. Do not initialize one merely to satisfy commit steps; each task ends with a verified test checkpoint instead.

## File Map

- Modify `agent-lab/ui/index.html`: application shell, mode navigation, chat/run surfaces, workspace dialog, run dialog, details drawer, semantic/ARIA structure, cache-busted asset URLs.
- Replace `agent-lab/ui/styles.css`: one token system, desktop shell, modes, messages, run overview, dialogs, drawer, responsive behavior, focus, reduced motion.
- Modify `agent-lab/ui/app.js`: presentation state, mode switching, dialog/drawer behavior, run surface rendering, details tabs, copy, and event wiring; preserve API calls and polling.
- Modify `agent-lab/ui/test_ui_contract.mjs`: source-level contracts for the new structure and retained workflow/retry behavior.
- Modify `design-qa.md`: approved brief, screenshots/viewports exercised, interaction evidence, automated checks, and remaining limitations.

## Review Focus

- Empty records: no chats, no runs, no messages, no artifacts, or missing workflow data must produce an actionable empty state rather than a broken panel; Task 1 adds static empty-state contracts and Task 4 verifies them live.
- Long content: session IDs, Windows paths, task text, messages, and filenames must wrap or truncate without horizontal document overflow; Task 3 adds overflow rules and Task 4 measures document width.
- Active polling: switching from a running run to a chat, or from a busy chat to Runs, must not force the wrong surface back onscreen; Task 2 tests mode ownership in the source contract and Task 4 exercises both pollers.
- Recoverable jobs: failed/interrupted chats must show retry, disable Send, and keep the composer context visible; Task 2 preserves `renderJobRecovery()` and Task 4 verifies the visible state.
- Narrow interaction: navigation, workspace management, run launch, Details, composer, and file preview must remain reachable at phone width with Escape/close behavior and sensible focus restoration; Tasks 2-3 implement it and Task 4 verifies it.

---

### Task 1: Lock the New Shell Contract and Rewrite the Markup

**Files:**
- Modify: `agent-lab/ui/test_ui_contract.mjs`
- Modify: `agent-lab/ui/index.html`

**Interfaces:**
- Consumes: Existing DOM IDs referenced by `agent-lab/ui/app.js`.
- Produces: `chatsModeButton`, `runsModeButton`, `chatSurface`, `runSurface`, `workspaceDialog`, `runDialog`, `detailsBackdrop`, and the retained IDs consumed by Tasks 2-4.

- [ ] **Step 1: Convert the source contract to named Node tests and add a failing shell test**

Replace the top-level assertions with `node:test` groups so each implementation task can run its own contract independently. Keep the existing workflow/retry assertions and add this structure test:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const uiDir = fileURLToPath(new URL("./", import.meta.url));
const html = readFileSync(`${uiDir}index.html`, "utf8");
const app = readFileSync(`${uiDir}app.js`, "utf8");
const css = readFileSync(`${uiDir}styles.css`, "utf8");

test("shell exposes separate Chats and Runs modes", () => {
  for (const id of [
    "chatsModeButton", "runsModeButton", "chatSurface", "runSurface",
    "workspaceDialog", "runDialog", "rightRail", "detailsBackdrop",
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /aria-controls="chatSurface"/);
  assert.match(html, /aria-controls="runSurface"/);
});

test("critical legacy capabilities remain mounted", () => {
  for (const id of [
    "projectSelect", "projectName", "workspacePath", "sessionSearch",
    "sessionList", "runList", "taskPreset", "taskText", "useGates",
    "reasoningLevel", "workflowSteps", "chatMessages", "chatInput",
    "retryJobButton", "activity", "fileList", "filePreview", "rawOutput",
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
});
```

- [ ] **Step 2: Run the shell test and verify the expected failure**

Run:

```powershell
node --test --test-name-pattern "shell exposes" agent-lab/ui/test_ui_contract.mjs
```

Expected: FAIL because the mode surfaces and dialogs do not exist yet.

- [ ] **Step 3: Rewrite `index.html` around the approved shell**

Use this structural skeleton and place all retained controls inside the indicated regions:

```html
<body>
  <div class="app-shell">
    <header class="app-header">
      <button id="sidebarToggle" class="icon-button mobile-only" type="button"
        aria-controls="sidebar" aria-expanded="false" aria-label="Open navigation"></button>
      <a class="brand" href="#" aria-label="Agent Lab home"><span class="brand-mark">AL</span><span>Agent Lab</span></a>
      <button id="mobileWorkspaceButton" class="project-context" type="button"
        aria-controls="workspaceDialog"><span id="topbarWorkspace">Scratch workspace</span></button>
      <div class="header-actions">
        <label class="reasoning-control" for="reasoningLevel">Reasoning <select id="reasoningLevel"></select></label>
        <span id="runStatus" class="status-badge idle" role="status"></span>
        <button id="inspectorToggle" type="button" aria-controls="rightRail" aria-expanded="false">Details</button>
      </div>
    </header>

    <main id="layout" class="layout" data-mode="chats">
      <aside id="sidebar" class="navigation-rail">
        <button id="workspaceDialogTrigger" class="project-switcher" type="button" aria-controls="workspaceDialog"></button>
        <div class="mode-switcher" role="tablist" aria-label="Work mode">
          <button id="chatsModeButton" role="tab" aria-selected="true" aria-controls="chatSurface">Chats</button>
          <button id="runsModeButton" role="tab" aria-selected="false" aria-controls="runSurface">Runs</button>
        </div>
        <section id="chatNavigation" class="navigation-mode">
          <!-- Move the existing #newChatButton, #sessionSearch, and #sessionList here without renaming them. -->
        </section>
        <section id="runNavigation" class="navigation-mode" hidden>
          <!-- Move the existing new-run action, #refreshRuns, and #runList here without renaming retained IDs. -->
        </section>
      </aside>

      <section class="work-surface">
        <section id="chatSurface" class="mode-surface">
          <!-- Move the existing chat header, #chatMessages, #retryJobButton, #chatInput, #chatNote, and #sendButton here. -->
        </section>
        <section id="runSurface" class="mode-surface" hidden>
          <!-- Add #runEmptyState and #runOverview exactly as specified in Step 4. -->
        </section>
      </section>

      <div id="detailsBackdrop" class="drawer-backdrop" hidden></div>
      <aside id="rightRail" class="details-drawer" aria-label="Details" aria-hidden="true">
        <!-- Move #inspectorContent, #workflowSteps, #activity, #fileList, #filePreview, and #rawOutput into four tab panels. -->
      </aside>
    </main>
  </div>

  <dialog id="workspaceDialog" aria-labelledby="workspaceDialogTitle">
    <!-- Move all existing project selection, creation, attached-folder, status, and workspace action controls here. -->
  </dialog>
  <dialog id="runDialog" aria-labelledby="runDialogTitle">
    <!-- Move #taskPreset, #taskText, #useGates, #runTarget, #runButton, and #launchNote here. -->
  </dialog>
</body>
```

Retain all existing IDs inside the new structure. Put `projectSelect`, project creation, attached-folder fields, `workspaceStatus`, and workspace actions in `workspaceDialog`. Put `taskPreset`, `taskText`, `useGates`, `runTarget`, `runButton`, and `launchNote` in `runDialog`. Remove the unsupported attachment button. Put the existing workflow, inspector content, activity, artifacts, file preview, and raw output inside `rightRail`.

- [ ] **Step 4: Add clear run and empty surfaces**

Add a run overview with stable IDs for Task 2:

```html
<div id="runEmptyState" class="surface-empty">
  <h2>Select a run</h2>
  <p>Inspect a previous run or start a new evaluation.</p>
  <button id="emptyNewRunButton" type="button">New run</button>
</div>
<article id="runOverview" hidden>
  <header class="record-header">
    <p id="runProjectLabel"></p>
    <h1 id="runTitle">Run</h1>
    <p id="runSummary"></p>
  </header>
</article>
```

- [ ] **Step 5: Run the markup contracts**

Run:

```powershell
node --test --test-name-pattern "shell exposes|critical legacy" agent-lab/ui/test_ui_contract.mjs
```

Expected: PASS for both named tests. Other new behavior/style tests may remain red until their tasks.

- [ ] **Step 6: Checkpoint**

Record the changed files and the exact passing command in the task log. Do not initialize Git.

---

### Task 2: Add Chats/Runs Mode State, Dialogs, Run Rendering, and Details Tabs

**Files:**
- Modify: `agent-lab/ui/test_ui_contract.mjs`
- Modify: `agent-lab/ui/app.js`

**Interfaces:**
- Consumes: DOM IDs produced by Task 1 and existing API functions `api()`, `loadRuns()`, `loadSessions()`, `createSession()`, `startRun()`, `renderWorkflow()`, `renderActivity()`, and `renderFiles()`.
- Produces: `setMode(mode, options)`, `openModal(dialogId, triggerId)`, `closeModal(dialogId)`, `setDetailsTab(tab)`, and `renderRunSurface(run)`.

- [ ] **Step 1: Add failing source contracts for presentation behavior**

Add:

```js
test("browser code owns mode, modal, and details presentation state", () => {
  assert.match(app, /mode:\s*["']chats["']/);
  assert.match(app, /function setMode\(/);
  assert.match(app, /function openModal\(/);
  assert.match(app, /function closeModal\(/);
  assert.match(app, /function setDetailsTab\(/);
  assert.match(app, /function renderRunSurface\(/);
  assert.match(app, /setMode\(["']runs["']/);
  assert.match(app, /setMode\(["']chats["']/);
});

test("workflow and retry contracts remain intact", () => {
  assert.match(app, /const WORKFLOW_PHASES/);
  assert.match(app, /function normalizeWorkflow/);
  assert.match(app, /function renderWorkflow/);
  assert.match(app, /function renderJobRecovery/);
  assert.match(app, /\/retry/);
  assert.match(app, /interrupted/);
});
```

- [ ] **Step 2: Run the presentation-state test and verify it fails**

Run:

```powershell
node --test --test-name-pattern "presentation state" agent-lab/ui/test_ui_contract.mjs
```

Expected: FAIL because the new functions do not exist.

- [ ] **Step 3: Extend the state object and implement mode switching**

Add these fields without changing API state:

```js
const state = {
  activeRun: null,
  activeSession: null,
  activeKind: null,
  activeRecord: null,
  selectedFile: null,
  sessionFilter: "",
  reasoningLevel: "standard",
  reasoningOptions: [],
  projects: [],
  sessions: [],
  runPollTimer: null,
  sessionPollTimer: null,
  tasks: [],
  mode: "chats",
  detailsTab: "overview",
  modalReturnFocus: new Map(),
};

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
    $(id).setAttribute("aria-selected", String(active));
    $(id).tabIndex = active ? 0 : -1;
  });
  if (focus) $(`${nextMode}ModeButton`).focus();
}
```

`selectSession()` calls `setMode("chats")` only after its session request succeeds. `selectRun()` calls `setMode("runs")` only after its run request succeeds. Polling renders the active record but never calls `setMode()`, preventing a background poll from stealing the visible mode.

- [ ] **Step 4: Implement native-dialog helpers and wire project/run launchers**

```js
function openModal(dialogId, triggerId) {
  const dialog = $(dialogId);
  const trigger = triggerId ? $(triggerId) : document.activeElement;
  if (trigger instanceof HTMLElement) state.modalReturnFocus.set(dialogId, trigger);
  if (!dialog.open) dialog.showModal();
}

function closeModal(dialogId) {
  const dialog = $(dialogId);
  if (dialog.open) dialog.close();
}

function restoreModalFocus(dialogId) {
  const trigger = state.modalReturnFocus.get(dialogId);
  state.modalReturnFocus.delete(dialogId);
  if (trigger?.isConnected) trigger.focus();
}
```

Wire `workspaceDialogTrigger` and `mobileWorkspaceButton` to `workspaceDialog`; wire the Runs-mode primary action and `emptyNewRunButton` to `runDialog`; wire explicit close buttons; use each dialog's `close` event to restore focus. Successful project selection/creation/opening and successful run launch close their dialog.

- [ ] **Step 5: Render a real selected-run surface**

```js
function renderRunSurface(run) {
  const summary = run.summary || {};
  $("runEmptyState").hidden = true;
  $("runOverview").hidden = false;
  $("runTitle").textContent = run.run_id;
  $("runSummary").textContent = summary.summary || `Status: ${statusLabel(run.status)}`;
  $("runProjectLabel").textContent = projectForPath(run.project)?.name ||
    (run.workspace_mode === "selected" ? "Existing folder" : "Scratch workspace");
}
```

Call it from `renderRun()`. Remove chat-specific subtitle mutations from run rendering. Keep `rawOutput`, workflow, activity, files, reasoning, status, and polling updates exactly as data sources.

- [ ] **Step 6: Replace inspector routing with four details tabs**

Replace the existing `state.inspectorTab` field with `state.detailsTab`. Use `overview`, `workflow`, `activity`, and `files` as tab values. `setDetailsTab(tab)` toggles `aria-selected`, `hidden`, and focus. Keep `renderInspector()` responsible for Overview content only; keep `renderWorkflow()`, `renderActivity()`, and `renderFiles()` targeting their dedicated tab panels.

The Overview content includes ID, status, model, reasoning, project, working directory, model/tool calls, response cap, host, and network state. Do not delete information formerly split across Session/Model/Environment.

- [ ] **Step 7: Adapt Details and navigation drawers without changing data flow**

Update `setInspectorOpen(open)` to set `.details-open`, `aria-expanded`, `aria-hidden`, and `detailsBackdrop.hidden`. Close Details from its close button, backdrop, and Escape. Mobile navigation retains its existing close-on-selection behavior and updates `aria-expanded`.

- [ ] **Step 8: Wire keyboard and mode controls**

Chats/Runs buttons respond to click and Left/Right arrows. Preserve Ctrl/Cmd+Enter sending, project-name Enter, reasoning changes, retry, file preview, task preset, and refresh behavior. Remove references to the deleted attachment button and legacy permanent run builder.

- [ ] **Step 9: Run source contracts and syntax checks**

Run:

```powershell
node --test agent-lab/ui/test_ui_contract.mjs
node --check agent-lab/ui/app.js
```

Expected: all Node tests PASS and syntax check exits 0.

- [ ] **Step 10: Checkpoint**

Record the changed files and both passing commands. Do not initialize Git.

---

### Task 3: Replace the Visual System and Responsive Layout

**Files:**
- Modify: `agent-lab/ui/test_ui_contract.mjs`
- Replace: `agent-lab/ui/styles.css`

**Interfaces:**
- Consumes: Classes and data attributes from Tasks 1-2.
- Produces: One coherent responsive CSS system for `.app-shell`, `.navigation-rail`, `.work-surface`, `.mode-surface`, `.details-drawer`, dialogs, messages, run overview, and mobile sheets.

- [ ] **Step 1: Add failing style contracts**

```js
test("styles define the approved visual and responsive system", () => {
  for (const token of ["#10141C", "#1A2130", "#EAECF1", "#8D91F7", "#65B8C7"]) {
    assert.match(css.toUpperCase(), new RegExp(token.toUpperCase()));
  }
  assert.match(css, /\.navigation-rail/);
  assert.match(css, /\.details-drawer/);
  assert.match(css, /dialog\[open\]/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.doesNotMatch(css, /text-transform:\s*uppercase/);
});
```

- [ ] **Step 2: Run the style test and verify it fails**

Run:

```powershell
node --test --test-name-pattern "approved visual" agent-lab/ui/test_ui_contract.mjs
```

Expected: FAIL against the legacy/override stylesheet.

- [ ] **Step 3: Replace `styles.css` with one token system**

Begin with the approved values and deliberate type roles:

```css
:root {
  color-scheme: dark;
  --ink: #10141c;
  --steel: #1a2130;
  --paper: #eaecf1;
  --slate: #969eae;
  --iris: #8d91f7;
  --cyan: #65b8c7;
  --amber: #d6a75f;
  --danger: #e07a82;
  --line: color-mix(in srgb, var(--paper) 13%, transparent);
  --line-strong: color-mix(in srgb, var(--paper) 22%, transparent);
  --ui-font: Bahnschrift, "Segoe UI Variable", "Segoe UI", sans-serif;
  --text-font: Aptos, "Segoe UI", sans-serif;
  --mono-font: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
  --header-height: 60px;
  --rail-width: 280px;
  --drawer-width: 360px;
}
```

Do not append an override layer. Organize the file once in this order: reset/tokens, header, layout, navigation, shared controls, chat, run surface, drawer/details, dialogs, utilities/status, responsive rules, reduced motion.

- [ ] **Step 4: Implement the desktop hierarchy**

Use a two-column base grid:

```css
.layout {
  min-height: 0;
  display: grid;
  grid-template-columns: var(--rail-width) minmax(0, 1fr);
  overflow: hidden;
}

.navigation-rail {
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  border-right: 1px solid var(--line);
  background: color-mix(in srgb, var(--ink) 88%, black);
}

.work-surface { min-width: 0; min-height: 0; position: relative; }
.details-drawer {
  position: fixed;
  inset: var(--header-height) 0 0 auto;
  width: min(var(--drawer-width), 92vw);
  transform: translateX(100%);
}
.details-open .details-drawer { transform: translateX(0); }
```

Messages must use a readable maximum measure; only user messages use a bounded colored surface. The model response should read as prose on the work surface. The composer remains visually anchored and does not cover the latest message.

- [ ] **Step 5: Implement dialogs, states, and meaningful focus**

Native dialogs use `::backdrop`, a maximum readable width, and full-width treatment on phones. Buttons, tabs, inputs, textareas, list items, file buttons, and disclosures receive `:focus-visible` treatment using Iris plus a non-color outline offset. Busy, blocked, failed, healthy, and selected states use text or icons in addition to color.

- [ ] **Step 6: Implement narrow and phone layouts**

At `1100px`, Details overlays instead of expecting spare canvas. At `760px`, navigation becomes a fixed sheet, header copy is abbreviated, the composer becomes compact, dialogs become near-full-screen, and touch targets remain at least 40px. At `480px`, hide nonessential hints while preserving project, status, modes, and primary actions.

Ensure the page root never horizontally scrolls:

```css
html, body { width: 100%; min-width: 0; overflow: hidden; }
*, *::before, *::after { box-sizing: border-box; }
.chat-content, .run-task, .mono-value, .file-name { overflow-wrap: anywhere; }
```

- [ ] **Step 7: Respect reduced motion**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
```

- [ ] **Step 8: Run the complete UI source contract and syntax check**

Run:

```powershell
node --test agent-lab/ui/test_ui_contract.mjs
node --check agent-lab/ui/app.js
```

Expected: all tests PASS; syntax check exits 0.

- [ ] **Step 9: Checkpoint**

Record the changed files and passing commands. Do not initialize Git.

---

### Task 4: Verify Real Workflows, Fix Visual Defects, and Publish the Cache-Busted UI

**Files:**
- Modify: `agent-lab/ui/index.html`
- Modify if defects are found: `agent-lab/ui/styles.css`
- Modify if defects are found: `agent-lab/ui/app.js`
- Modify: `design-qa.md`

**Interfaces:**
- Consumes: Complete redesigned static UI from Tasks 1-3 and existing local server at `http://127.0.0.1:8787`.
- Produces: Fresh automated evidence, desktop and narrow browser evidence, cache-busted public assets, and an honest QA record.

- [ ] **Step 1: Run the full automated suite before browser review**

Run:

```powershell
$pythonExe = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
node --test agent-lab/ui/test_ui_contract.mjs
node --check agent-lab/ui/app.js
& $pythonExe -m py_compile agent-lab/ui/server.py
& $pythonExe -m unittest discover -s agent-lab/ui -p 'test_*.py'
```

Expected: Node tests PASS, JavaScript syntax exits 0, Python compile exits 0, and all UI/server workflow tests PASS.

- [ ] **Step 2: Confirm the local service is healthy and serving the edited files**

Run:

```powershell
$health = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 10
$page = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/' -TimeoutSec 10
$health.Content
$page.StatusCode
```

Expected: health body contains `"status": "ok"`; page status is 200. If the existing server does not pick up static files, restart only the Agent Lab UI process using the existing project script, then repeat.

- [ ] **Step 3: Desktop browser test Chats mode**

At a wide viewport, verify in the rendered page:

- Active project, Chats/Runs mode, selected conversation, model/reasoning, status, New chat, and Details are obvious without scrolling.
- Conversation gets the dominant width; model prose is readable; long messages and paths do not overflow.
- Search filters the conversation list.
- Selecting another conversation keeps Chats visible.
- New chat opens in the selected project context.
- Interrupted/failed fixtures show retry and disable Send; a normal ready chat allows Send.
- Details opens and closes; Overview, Workflow, Activity, and Files each expose the expected existing data.
- File preview opens from Files and closes without losing the selected record.

- [ ] **Step 4: Desktop browser test Runs mode**

Verify:

- Switching to Runs replaces the chat list and main surface without changing project context.
- Selecting a historical run shows its task, status, project, summary, workflow, artifacts, and raw output.
- New run opens the focused launch dialog with preset, editable task, gates, reasoning, and target project.
- Cancel restores focus without changing state.
- Start run closes the dialog, selects the new run, shows running state, and polling updates the run without switching modes unexpectedly.

Use a harmless existing preset and scratch workspace for the live launch. Do not point the local model at an unrelated user folder.

- [ ] **Step 5: Test workspace management**

Open the workspace dialog and verify Scratch, existing managed projects, project creation controls, and attached-folder controls are understandable. Select an existing managed project, confirm the header/rail/run target update, then return to the user's original project context. Do not create or delete a project solely for visual testing.

- [ ] **Step 6: Test compact and phone-sized layouts**

At widths around 760px and 390px, verify:

- `document.documentElement.scrollWidth <= document.documentElement.clientWidth`.
- Navigation opens as a sheet and closes after record selection.
- Chats/Runs mode remains reachable.
- Active project and status remain visible.
- Composer, Send, and retry remain reachable above the browser chrome.
- Workspace and run dialogs scroll internally without trapping content offscreen.
- Details overlays, closes with its button and Escape, and file preview remains readable.
- All visible controls have usable touch targets and visible keyboard focus.

- [ ] **Step 7: Inspect browser errors**

Read the Agent Lab tab's console logs. Expected: no new JavaScript exceptions, rejected promises, missing-element errors, or failed static assets. Fix any defect, rerun the smallest owning test, then rerun the complete Node contract.

- [ ] **Step 8: Update asset versions and QA record**

After the final code change, change both asset query strings in `index.html` to one new shared value such as:

```html
<link rel="stylesheet" href="styles.css?v=20260920-studio-1">
<script src="app.js?v=20260920-studio-1"></script>
```

Update `design-qa.md` with the approved intent, exact automated command results, desktop and phone widths tested, interactions exercised, public verification status, and any limitation that remains. Do not call the redesign complete from screenshots alone.

- [ ] **Step 9: Verify through the public tunnel**

Run read-only requests:

```powershell
$page = Invoke-WebRequest -UseBasicParsing -Uri 'https://lab.lobotomy.help/' -TimeoutSec 20
$health = Invoke-WebRequest -UseBasicParsing -Uri 'https://lab.lobotomy.help/api/health' -TimeoutSec 20
$page.StatusCode
$health.Content
```

Expected: page status 200 and health contains `"status": "ok"`. Open the public page, confirm it references `20260920-studio-1`, and repeat the primary desktop smoke path there.

- [ ] **Step 10: Final verification gate**

Rerun every command from Step 1 after the last defect fix or cache-bust edit. Read the full output. Only then report the exact passing counts, viewports, interactions, public status, and remaining limitations.

- [ ] **Step 11: Checkpoint**

Record all changed files and final evidence. Because this workspace is not a Git repository, report that no commit or PR was created.

