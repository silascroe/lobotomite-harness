# Agent Lab Interface Redesign

## Intent

Agent Lab should feel like a coherent coding-agent workbench rather than a monitoring dashboard with a chat box trapped inside it. The redesign will use the proven structural grammar of Codex: persistent project and conversation navigation, a dominant work surface, and secondary operational detail that appears when requested. It will not copy Codex's color, typography, branding, or exact component styling.

Agent Lab is an internal testing harness, not a commercial product. Its interface must therefore make both ordinary conversations and repeatable benchmark runs easy to start, inspect, and compare. Chats and runs remain separate modes in this slice. They share a selected project and the same details machinery, but they are not merged into a new backend concept.

## Current problem

The current page permanently presents projects, conversation history, run creation, recent runs, workflow, chat, inspector tabs, activity, artifacts, and raw output. These surfaces have similar visual weight and several independent scrolling regions. The actual conversation is compressed between two dense rails, while small labels and metadata carry too much of the navigation burden.

The stylesheet also contains two visual systems: the original rules and a later override layer. That made incremental polish possible, but it now obscures hierarchy and makes responsive behavior harder to reason about. Another polishing pass would preserve the congestion instead of correcting it.

## Goals

- Make the active project, current mode, selected record, model, reasoning level, and runtime status understandable at a glance.
- Give the conversation or selected run most of the viewport.
- Keep project selection and conversation history persistent without turning project creation into permanent chrome.
- Keep chats and runs visibly separate while allowing both to operate on the selected project.
- Preserve every existing capability: managed projects, scratch work, existing folders, searchable chats, reasoning selection, run presets, completion gates, workflow state, retry, activity, artifacts, file preview, inspector data, recent runs, and raw output.
- Remove competing scroll regions where possible and ensure the document remains usable on a laptop, narrow browser pane, and phone-sized viewport.
- Preserve existing server APIs, harness behavior, persisted records, and filesystem semantics.
- Make the interface visually authored and presentable without turning an experimental tool into decorative theater.

## Non-goals

- No harness, model, workflow, project-storage, Telegram, Discord, tunnel, or deployment changes.
- No attempt to merge chats and runs in the backend.
- No new framework, build system, remote font, image dependency, or UI library.
- No imitation of Codex branding, exact colors, icons, spacing, or proprietary details.
- No removal of diagnostic information; secondary information moves behind deliberate controls.
- No new benchmark or model evaluation work during the redesign.

## Information architecture

The application has three persistent concepts and two work modes:

1. **Project context**: scratch, managed project, or attached folder. This context applies to new chats and new runs.
2. **Navigation**: projects, mode switcher, and the list belonging to the active mode.
3. **Details**: workflow, session/model/environment information, activity, artifacts, file preview, and raw output.
4. **Chats mode**: interactive conversation with the local model.
5. **Runs mode**: benchmark/custom-task creation and inspection of completed or active runs.

Chats and runs use the same shell but have distinct main surfaces. Selecting a chat opens the conversation and composer. Selecting a run opens a run overview with its task, status, workflow, artifacts, and output. Creating a run uses a focused launch sheet rather than an always-visible sidebar form.

## Desktop layout

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Agent Lab     Active project                         New   Details       │
├──────────────────┬───────────────────────────────────────────────────────┤
│ Project switcher │ Project / selected record       model · status      │
│                  │                                                       │
│ Chats | Runs     │ Conversation or run surface                         │
│                  │                                                       │
│ Search           │                                                       │
│ Record list      │                                                       │
│                  │                                                       │
│                  │ Composer in Chats mode / run actions in Runs mode    │
└──────────────────┴───────────────────────────────────────────────────────┘
                                                optional Details drawer →
```

The navigation rail is approximately 280 pixels wide and remains visually quiet. The main surface consumes the remaining width. The details drawer is closed by default and overlays or reduces the main surface depending on available width. It is not a permanent third column.

The header contains the brand, active project, context-aware primary action, reasoning control, status, and Details control. It does not repeat descriptive copy already clear from the selected mode.

## Navigation rail

The top of the rail contains a compact project switcher showing the active project and location class: scratch, managed, or attached. A nearby project-management action opens a workspace dialog containing project creation, managed-project selection, existing-folder attachment, and the return-to-scratch action.

Below the project switcher, a two-option mode control switches between Chats and Runs. It changes the list and primary action without changing the project.

Chats mode contains:

- A prominent `New chat` action.
- Search.
- Conversation list with readable titles, message count, age, and a restrained active state.

Runs mode contains:

- A prominent `New run` action.
- Recent runs with status, task title or run identifier, file count, and age when available.
- Status language that distinguishes active, complete, blocked, interrupted, and failed work.

The rail has one internal scrolling list. Project controls and mode controls remain fixed. The large task editor and completion-gate controls never live permanently in the rail.

## Chat surface

The chat header gives the selected conversation a readable title and shows the active project beneath it. Model, reasoning, and runtime status remain visible but secondary. Long session IDs and full paths move to Details.

Messages use a restrained two-voice treatment rather than boxed cards for every line. User messages receive a contained surface; model responses sit on the page with a readable measure. Author and time remain visible without becoming the dominant typography. Tool and workflow events stay out of the prose stream unless they require user action.

The composer anchors to the bottom of the main surface. It shows the target project, keyboard hint, and Send action. The unsupported attachment control is removed until the harness can act on it. Recoverable interrupted or failed jobs place a clear retry action immediately above the composer.

## Runs surface

Runs remain a separate mode because they serve evaluation rather than ordinary conversation. Selecting a run replaces the chat surface with:

- Run identifier and recorded summary.
- Run status and workflow phase.
- Target project/workspace.
- Start time, completion state, model, reasoning level, completion gates, and summary.
- Direct access to artifacts and raw output through Details.

`New run` opens a focused sheet containing the preset selector, editable task, completion-gate option, target-project confirmation, and Start run action. Launching closes the sheet and selects the new run. Existing server behavior and payloads remain unchanged.

## Details drawer

The Details control opens one drawer with four sections:

- **Overview**: session/run identity, status, project, working directory, model, reasoning, and environment.
- **Workflow**: phase progression, current summary, next action, and recovery state.
- **Activity**: chronological model/tool/run events.
- **Files**: artifacts and inline file preview.

Raw process output is available at the bottom under an explicit disclosure. Details preserve the existing data and inspector tabs concept without consuming a permanent third of the application.

On a wide desktop, the drawer may push the main surface inward. On narrower screens it overlays the surface and closes with a visible button, Escape, or backdrop action.

## Workspace dialog

Workspace management opens in a dialog because it is consequential but infrequent. It explains the three choices in user language:

- **Scratch**: temporary work isolated to one chat or run.
- **Managed project**: a persistent Agent Lab project reused across chats and runs.
- **Existing folder**: an explicitly chosen folder elsewhere on disk.

Creating or selecting a managed project updates the global project context and explains that new work will use it. Existing chats and runs retain their recorded workspace. The dialog reuses existing APIs and validation messages.

## Visual system

The visual direction is a precision instrument with the restraint of a well-made desktop tool. The memorable element is the active-project treatment and its continuity across the shell; decoration elsewhere stays quiet.

### Color

- **Deep navy** `#10141C`: application ground.
- **Blue steel** `#1A2130`: raised controls and selected surfaces.
- **Porcelain** `#EAECF1`: primary text.
- **Slate** `#969EAE`: secondary text.
- **Iris** `#8D91F7`: selection, focus, and primary action.
- **Instrument cyan** `#65B8C7`: healthy/connected state; restrained amber `#D6A75F` and red `#E07A82` are reserved for warning and failure.

The interface uses flat planes and meaningful separators instead of a grid of identical cards. Shadows are limited to overlays and the composer/drawer relationship. Border radius varies by purpose: small on controls, moderate on dialogs, and absent on structural regions.

### Typography

- **Bahnschrift** for navigation, headings, and controls, with Segoe UI Variable as fallback.
- **Aptos/Segoe UI** for ordinary interface text and message prose.
- **Cascadia Mono** only for paths, identifiers, token counts, and raw output.

Labels use sentence case. Body copy stays below roughly 80 characters per line. Model prose receives a comfortable line height and maximum measure. Tiny all-caps metadata, decorative eyebrows, and gratuitous monospace labels are removed.

### Motion

Motion only explains state change: drawer and dialog entrance, mode switch, sending state, and new activity. Reduced-motion preference removes nonessential transitions. There is no page-load choreography or blanket hover animation.

## Responsive behavior

At desktop widths, the navigation rail and main surface are visible; Details is optional. Below the compact breakpoint, the navigation rail becomes a drawer. The active project remains visible in the mobile header. The composer stays reachable without requiring the entire document to scroll to the bottom.

On phone-sized widths, Chats/Runs switching, record selection, and Details use full-height sheets. Dialog content becomes a full-width panel. Controls retain at least a comfortable touch target, text does not fall below readable sizes, and no horizontal document overflow is allowed.

## Accessibility and interaction rules

- Preserve semantic landmarks, labels, tab state, live regions, and status announcements.
- Every interactive control has visible keyboard focus.
- Dialogs trap focus while open, close with Escape, and restore focus to their launcher.
- Drawers expose correct expanded state and have explicit close controls.
- Color never carries status alone.
- Sending, run launch, project creation, and retry expose disabled/busy states.
- Search, message entry, project naming, and task editing remain fully keyboard-operable.
- Reduced-motion preference is respected.

## Implementation boundaries

`agent-lab/ui/index.html` will be structurally rewritten while preserving API-dependent element IDs where practical. New shell, mode controls, workspace dialog, run sheet, and details drawer elements will be added.

`agent-lab/ui/styles.css` will be replaced with one coherent token and responsive system. The current appended override layer will not be carried forward.

`agent-lab/ui/app.js` will keep all API calls and data normalization. Changes are limited to presentation state, mode switching, dialogs/drawers, rendering chats and runs in the new surfaces, clearer copy, and accessibility behavior.

`agent-lab/ui/test_ui_contract.mjs` will retain workflow and retry assertions and add structural assertions for Chats/Runs modes, workspace management, run launch, details, and preserved critical controls.

`design-qa.md` will be updated with the new visual brief, viewport checks, interaction checks, and honest remaining limitations. Static asset query versions will change so the public tunnel does not serve stale CSS or JavaScript.

No `server.py`, harness, persistence format, project model, or endpoint change is planned. If implementation reveals a missing API required for the approved design, work stops and the scope is reclassified before touching the backend.

## Verification

The redesign is complete only when all of the following are freshly verified:

- `node --check agent-lab/ui/app.js` passes.
- `node agent-lab/ui/test_ui_contract.mjs` passes.
- Existing Python UI/server workflow tests pass.
- Local health and the public page return successfully with the new cache-busted assets.
- Desktop visual review covers Chats mode, Runs mode, workspace dialog, run sheet, Details, file preview, empty states, populated states, busy/recoverable states, and long content.
- Narrow and phone-sized review confirms navigation, sheets, composer reachability, touch targets, document width, and scrolling.
- Keyboard review covers mode switching, dialogs, composer, Send, retry, and drawer dismissal.
- Browser console inspection shows no new errors.
- Existing project selection, new chat, run launch, reasoning selection, retry, activity, artifacts, and file preview interactions still work against the live local server.

## Success criteria

A first-time viewer should understand within a few seconds which project is active, whether they are in Chats or Runs, what record is selected, how to start new work, and where secondary evidence lives. The conversation or run must feel like the primary object rather than one panel among many. The result should be structurally familiar to a Codex user, visually distinct to Agent Lab, and honest about the harness's experimental purpose.

