# Agent Lab Native Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent, persistent, visible workflow layer to Agent Lab so local coding runs expose their phase, evidence, and next action.

**Architecture:** A pure Python workflow module owns states and transitions. The existing harness records and exposes that state through its current run/session artifacts and JSON action protocol. The existing web console renders the snapshot as a phase rail and inspector detail, with no new runtime dependency or API family.

**Tech Stack:** Python 3.12 standard library, existing `unittest` suite, existing vanilla JavaScript/CSS UI, JSONL events and JSON snapshots.

**Spec:** `docs/superpowers/specs/2026-09-19-agent-lab-workflow-design.md`

## Global Constraints

- The reference checkout at `.research/superpowers-upstream` is read-only research material and must not be imported or invoked.
- The workflow stores operational summaries and evidence references only; it must not expose or claim to persist hidden chain-of-thought.
- Existing path checks, command allowlists, project selection, reasoning controls, and JSON action protocol remain compatible.
- No new Python, Node, or browser dependency may be installed.
- Invalid workflow input must return a reportable error without replacing the last valid snapshot.
- The UI must remain usable when workflow data is absent on legacy session/run records.

## Review Focus

- A stale or malformed `workflow.json` must not make a legacy session unreadable.
- A model checkpoint must not be able to escape the run directory through an artifact path.
- Automatic tool evidence must not move a workflow backward from `plan`, `verify`, or `review`.
- A failed command must not be presented as successful verification.
- The compact phase rail must not create a new page-scroll trap at desktop or narrow widths.

PowerShell command variables used below:

```powershell
$py = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
```

---

### Task 1: Pure workflow state machine

**Files:**
- Create: `agent-lab/harness/workflow.py`
- Create: `agent-lab/harness/test_workflow.py`

**Interfaces:**
- Produces `PHASES`, `WorkflowError`, `new_workflow()`, `transition()`, `observe_tool()`, `load_workflow()`, and `save_workflow()` for later tasks.

- [x] **Step 1: Write the failing tests**

Add tests for the initial snapshot, valid repair-loop transitions, rejected unknown/backward transitions, automatic evidence mapping, and malformed-file fallback.

- [x] **Step 2: Run the focused tests and verify they fail for the missing module**

Run:

```powershell
& $py -m unittest discover -s agent-lab/harness -p 'test_workflow.py' -v
```

Expected: import errors because `workflow.py` does not exist yet.

- [x] **Step 3: Implement the minimal pure module**

Use a plain dictionary contract so JSON snapshots remain easy to inspect. Implement explicit transition validation, ISO timestamps, artifact path validation using relative POSIX-looking paths, and conservative `observe_tool()` mapping.

- [x] **Step 4: Run the focused tests and verify they pass**

Run the same command. Expected: all workflow tests pass with no warnings.

- [x] **Step 5: Record the task result in the ledger**

Append the command and pass count to `.superpowers/sdd/agent-lab-workflow/progress.md`.

### Task 2: Harness protocol and durable snapshots

**Files:**
- Modify: `agent-lab/harness/agent_harness.py`
- Modify: `agent-lab/harness/test_agent_harness.py`
- Modify: `agent-lab/harness/config.json`

**Interfaces:**
- Consumes the pure workflow functions from Task 1.
- Produces the `workflow_checkpoint` JSON action, `workflow.json` snapshots, `workflow_phase` events, and `workflow` fields in run summaries.

- [x] **Step 1: Add failing integration tests**

Test that a prepared harness creates an `intake` snapshot, that dispatching `workflow_checkpoint` persists a `plan` snapshot and event, that an invalid artifact path is rejected, and that a failed command does not advance the state to `verify`.

- [x] **Step 2: Run the focused integration tests and verify the new assertions fail**

Run:

```powershell
& $py -m unittest discover -s agent-lab/harness -p 'test_agent_harness.py' -v
```

Expected: the pre-existing tests pass but the new workflow assertions fail because the harness has no workflow state or action.

- [x] **Step 3: Integrate the workflow into the harness**

Register `workflow_checkpoint` beside the existing actions, add its JSON shape to both system prompts, initialize and persist the state in `prepare()`, call `observe_tool()` after tool results, and include the snapshot in `save_summary()`. Keep failed `run_command` results out of automatic verify advancement.

- [x] **Step 4: Run the focused integration tests and then the existing suite**

Run:

```powershell
& $py -m unittest discover -s agent-lab/harness -p 'test_*.py'
```

Expected: both commands exit 0 and report no failures.

- [x] **Step 5: Record the task result in the ledger**

Append the test commands and pass counts.

### Task 3: Interactive session and run state exposure

**Files:**
- Modify: `agent-lab/ui/server.py`
- Create: `agent-lab/ui/test_server_workflow.py`

**Interfaces:**
- Consumes the harness snapshot and workflow loader from Task 1/2.
- Produces `workflow` in `/api/sessions/:id` and `/api/runs/:id` records without adding a second source of truth.

- [x] **Step 1: Add failing server-state tests**

Use temporary session/run directories and assert that state serialization includes a fallback `intake` workflow and that a live interactive session exposes its current snapshot.

- [x] **Step 2: Run the focused server tests and verify the new assertions fail**

Run:

```powershell
& $py -m unittest discover -s agent-lab/ui -p 'test_server_workflow.py' -v
```

Expected: import or assertion failures because server state currently has no workflow field.

- [x] **Step 3: Add workflow state to session metadata and run state**

Load the snapshot from the run/session directory with the pure fallback helper, include it in `save_meta()`, `state()`, and `run_state()`, and leave the existing API shapes intact for all other fields.

- [x] **Step 4: Run the focused server tests and the Python suite**

Run the focused command followed by the full harness discovery command. Expected: exit 0 with all tests passing.

- [x] **Step 5: Record the task result in the ledger**

Append the test commands and pass counts.

### Task 4: Visible workflow rail and inspector detail

**Files:**
- Modify: `agent-lab/ui/index.html`
- Modify: `agent-lab/ui/app.js`
- Modify: `agent-lab/ui/styles.css`

**Interfaces:**
- Consumes `record.workflow` from existing run/session polling responses.
- Produces a phase rail, current-phase summary, next-action copy, and workflow-aware activity entries.

- [x] **Step 1: Add the workflow rail markup and renderer contract**

Add a `workflowRail` container beneath the workspace heading with stable IDs for phase nodes, `workflowSummary`, and `workflowNext`. Add renderer functions that normalize missing workflow data to `intake` and escape all server-provided text.

- [x] **Step 2: Add the visual treatment**

Style the rail using existing variables, compact spacing, active/complete/blocked states, and narrow-width wrapping. Keep the center column’s existing flex/overflow rules and do not add a second page-level scroll container.

- [x] **Step 3: Connect run/session rendering and activity copy**

Call the workflow renderer from both `renderRun()` and `renderSession()`. Add `workflow_phase` event copy and ensure polling refreshes the rail with the same record update used for chat/activity.

- [x] **Step 4: Run syntax and browser-facing checks**

Run:

```powershell
& $node --check agent-lab/ui/app.js
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/health | Select-Object -ExpandProperty StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/reasoning-levels | Select-Object -ExpandProperty StatusCode
```

Expected: JavaScript syntax succeeds and both API requests return HTTP 200. If the UI server is not running, start it with the existing script and repeat the checks.

- [x] **Step 5: Record the task result in the ledger**

Append the syntax/API evidence.

### Task 5: Documentation and final verification

**Files:**
- Modify: `agent-lab/README.md`
- Create: `docs/research/superpowers-reference-review.md`

**Interfaces:**
- Documents the independent workflow contract and the pinned reference checkout.

- [x] **Step 1: Document the user-facing workflow**

Explain the phase rail, checkpoint evidence, persistent artifacts, and the fact that the reference clone is not a runtime dependency.

- [x] **Step 2: Document the reference review**

Record the pinned commit, repository inventory, the behavior patterns retained, the patterns deliberately excluded, and the license boundary.

- [x] **Step 3: Run the complete verification set**

Run:

```powershell
& $py -m unittest discover -s agent-lab/harness -p 'test_*.py'
& $node --check agent-lab/ui/app.js
& $py -m py_compile agent-lab/harness/agent_harness.py agent-lab/harness/workflow.py agent-lab/ui/server.py
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/health | Select-Object -ExpandProperty StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/projects | Select-Object -ExpandProperty StatusCode
```

Expected: all test and syntax commands exit 0; both HTTP status checks print `200`.

- [x] **Step 4: Perform a fresh self-review against the spec**

Check each goal and non-goal, inspect the final diff by file, and record any deferred minor issues in the ledger. Because the workspace is not a Git checkout, use the explicit changed-file list and file contents instead of a commit range.

- [x] **Step 5: Report the implementation, evidence, and any limitations**

Include the exact reference commit, changed files, test output counts, and the fact that the design is a native v1 rather than a full Superpowers clone.

