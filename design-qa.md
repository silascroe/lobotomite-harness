# Agent Lab interface redesign QA

Date: 2026-09-20
Result: interface redesign and second polish pass passed; local model backend unavailable during the final launch test

## Approved direction

Agent Lab now uses a coding-workbench structure: persistent project and record navigation, separate Chats and Runs modes, a dominant work surface, native project/run dialogs, and an optional Details drawer. The design is structurally familiar without copying Codex branding, color, typography, or component styling.

The redesign and behavior changes remain UI-facing. Existing server APIs, harness behavior, filesystem semantics, projects, sessions, runs, workflow data, retry behavior, artifacts, and raw output are preserved; the server only gained an explicit static route for the new favicon asset.

The second polish pass gives the workbench a blackened-olive, bone, copper, and patinated-mint palette rather than extending the old blue-violet system. It also turns nested JSON diagnostics in run summaries into readable one-line explanations while leaving raw process output available in Details.

The branding pass adds a native SVG favicon: a small copper portal/agent mark with a mint core, designed to stay legible at browser-tab sizes and to match the current palette.

## Automated evidence

- `node --test agent-lab/ui/test_ui_contract.mjs`: 13/13 tests passed.
- `node --check agent-lab/ui/app.js`: exit 0.
- Python compilation of `agent-lab/ui/server.py`: exit 0.
- `python -m unittest discover -s agent-lab/ui -p 'test_*.py'`: 11/11 tests passed.
- Local `/api/health`: `{"status":"ok","local_only":true}`.
- Local page: HTTP 200 and asset version `20260920-studio-7`.
- Favicon asset: `favicon.svg?v=20260920-studio-8`.

## Browser evidence

Tested at 1920×911, 760×900, and 390×844.

- Desktop Chats: loaded 36 persisted sessions, rendered conversation history, filtered search to one matching session, preserved the selected project, and kept the composer reachable.
- Desktop Runs: loaded 13 persisted runs, selected historical success/error records, kept Runs mode stable, and rendered recorded summaries and status.
- Details: Overview, Workflow, Activity, and Files tabs opened; `answer.txt` rendered in the inline preview; preview returned to the file index; raw output remained available.
- Workspace dialog: showed Scratch, two managed project choices, project creation, and existing-folder attachment; closing restored focus and did not change project context.
- Run dialog: showed preset, editable task, completion gates, active target project, and Start run; cancel/close behavior worked.
- Live launch: created and selected `run-ui-20260920-113904` in scratch, closed the dialog, and showed Running without switching modes. The run then honestly became Error because nothing was listening at `127.0.0.1:8080`; this is a model-runtime condition, not a frontend failure.
- Responsive: no horizontal overflow at 760px or 390px; navigation became a sheet; Details became an overlay; dialogs fit and remained internally usable; Send remained above the viewport edge.
- Accessibility: mode and details tabs expose selection state; mobile icon buttons retain names; closed off-canvas regions are inert; native dialogs restore focus; visible keyboard focus is defined; reduced motion is respected.
- Browser console: no JavaScript errors or warnings after the final interaction pass.

Second polish browser checks:

- Public Chats hydrated its persisted conversations after the initial empty-state paint; Runs loaded 13 records.
- Public Runs selected `run-ui-20260920-113904`; the main surface showed the concise endpoint failure without exposing nested JSON, and Details opened and closed with Escape.
- The new palette was visually checked at the desktop viewport; no layout rules changed in this pass, so the prior 760px and 390px responsive evidence remains applicable.

Fresh-load behavior check:

- A cold public reload opened the neutral Local conversation surface without selecting or creating a historical session; persisted chats remained available in the sidebar.
- Explicitly selecting `chat-20260919-044749` still opened its saved conversation normally.

Branding check:

- Public HTML references the SVG favicon and the asset returns HTTP 200 through the live tunnel.
- The favicon uses the same copper/mint/olive palette as the interface and contains no raster dependency.

## Public evidence

- `https://lab.lobotomy.help/`: HTTP 200.
- `https://lab.lobotomy.help/api/health`: `{"status":"ok","local_only":true}`.
- Public HTML references `styles.css?v=20260920-studio-7` and `app.js?v=20260920-studio-7`.
- Public browser smoke test loaded 36 chats and 13 runs, selected `qwen-tool-battery-20260919`, opened Details, and produced no console errors.

## Known runtime limitation

The UI service and public Cloudflare route are healthy. The local OpenAI-compatible model endpoint at `http://127.0.0.1:8080/v1/chat/completions` was not running during final QA, so a newly launched run could not complete model work. No claim is made that the model backend is healthy.

