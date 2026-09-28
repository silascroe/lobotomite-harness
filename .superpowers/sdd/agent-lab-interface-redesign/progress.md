# SDD ledger — plan: docs/superpowers/plans/2026-09-20-agent-lab-interface-redesign.md

Ruling: The workspace is not a Git repository, so worktree, task-start, task-done, commit, and review-package scripts are unavailable — use exact per-task test checkpoints and final browser evidence without initializing Git — cost if wrong: weaker rollback and provenance than a commit-backed execution.
Pre-flight: Task 1 produces DOM IDs consumed by Task 2; the plan and spec agree on Chats/Runs surfaces, native dialogs, and the Details drawer.
Pre-flight: Task 2 produces mode state, tab state, and dialog behavior consumed by Task 3 selectors; the plan and spec agree on the classes and data-mode contract.
Pre-flight: Tasks 1-3 produce the static interface consumed by Task 4; server routes and payloads remain unchanged.
Ruling: Historical run payloads have no original task text — render the run ID and recorded summary rather than inventing or changing the server contract — cost if wrong: older runs expose less context than they would with a future persisted task field.
Task 1: complete (files: agent-lab/ui/test_ui_contract.mjs, agent-lab/ui/index.html; tests: node --test --test-name-pattern "shell exposes|critical legacy" agent-lab/ui/test_ui_contract.mjs → 2/2 pass)
Task 2: complete (files: agent-lab/ui/test_ui_contract.mjs, agent-lab/ui/app.js; tests: node --test agent-lab/ui/test_ui_contract.mjs → 4/4 pass; node --check agent-lab/ui/app.js → exit 0)
Task 3: complete (files: agent-lab/ui/test_ui_contract.mjs, agent-lab/ui/styles.css; tests: node --test agent-lab/ui/test_ui_contract.mjs → 5/5 pass; node --check agent-lab/ui/app.js → exit 0)
Task 4: complete (files: agent-lab/ui/index.html, agent-lab/ui/app.js, agent-lab/ui/styles.css, agent-lab/ui/test_ui_contract.mjs, design-qa.md; tests: Node 9/9, Python 11/11, JavaScript syntax and Python compile exit 0; browser: 1920x911, 760x900, 390x844; public page and health HTTP 200; asset 20260920-studio-4; console clean)
Final review: self-review (no subagent tool)
Final: fixed stale active-project mutation when selecting historical records — selecting historical records preserves the active project context RED→GREEN, suite 9/9
Final: fixed closed mobile navigation and Details remaining keyboard-reachable — closed off-canvas regions are removed from keyboard navigation RED→GREEN, suite 9/9
Final: no Critical, Important, or deferred Minor findings remain.
Ruling: Preserve this plan workspace because there is no Git history to carry the execution record — deleting it would erase the only task ledger — cost if wrong: one small retained scratch directory.

Second polish pass: planned and completed a focused visual/runtime cleanup without changing the server contract. Rulings: move the palette to blackened olive, bone, copper, and patinated mint; keep existing component structure and interaction semantics; make run diagnostics readable on the primary surface while retaining raw output in Details. Cost if wrong: a stronger visual identity could be less familiar than the prior blue-violet palette, so the public browser check was required before completion.
Second polish pass: complete (files: agent-lab/ui/styles.css, agent-lab/ui/app.js, agent-lab/ui/index.html, agent-lab/ui/test_ui_contract.mjs, design-qa.md; tests: Node 11/11, Python 11/11, JavaScript syntax and Python compile exit 0; local and public health HTTP 200; asset 20260920-studio-6; public Runs and Details smoke check passed)
Fresh-load correction: complete (files: agent-lab/ui/app.js, agent-lab/ui/index.html, agent-lab/ui/test_ui_contract.mjs, design-qa.md; ruling: bootstrap may list historical conversations but must not select or create one; explicit selection and send-time creation remain user-initiated; regression: Node 12/12, public cold reload blank, explicit historical selection verified; asset 20260920-studio-7)
Branding pass: complete (files: agent-lab/ui/favicon.svg, agent-lab/ui/index.html, agent-lab/ui/server.py, agent-lab/ui/test_ui_contract.mjs, agent-lab/ui/test_server_workflow.py, design-qa.md; native SVG favicon uses the Agent Lab copper/mint mark; static route was added and covered by a server regression; regression: Node 13/13 and Python 12/12; public asset wired with cache-busted `studio-8` query)

