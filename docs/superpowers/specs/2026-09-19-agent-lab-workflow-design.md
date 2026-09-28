# Agent Lab Native Workflow Design

## Intent

Agent Lab should give Gemma and Quinn a durable, inspectable development workflow inspired by the useful ideas found in Superpowers, while remaining an independent implementation. The reference checkout at `.research/superpowers-upstream` is research material only; it is not installed, imported, or placed on the model runtime path.

The first slice is deliberately narrow. It adds workflow state, explicit checkpoints, durable evidence, and a visible UI stage rail. It does not attempt to reproduce Superpowers' skill library, subagent orchestration, worktree management, or host-specific plugin adapters.

## Current problem

Agent Lab already has real project folders, constrained tools, reasoning levels, transcripts, event logs, and a console. What it does not have is a durable answer to four questions:

1. What phase is the agent in?
2. What evidence caused it to move there?
3. What will it do next?
4. Did it inspect, design, plan, implement, verify, and review, or did it simply jump into edits?

The current activity list records individual tool calls, but the model and user must reconstruct the larger workflow from those calls. That is exactly where a small local model loses the plot.

## Goals

- Represent a run or interactive request with a small, stable workflow state machine.
- Persist the current state beside the existing run/session artifacts.
- Give the model a `workflow_checkpoint` action with a strict, machine-readable shape.
- Automatically advance the visible phase when ordinary tool evidence makes the phase obvious.
- Preserve the current tool protocol and project-folder safety rules.
- Expose phase, status, summary, next action, and artifact paths through existing run/session state APIs.
- Show the phase and next action in the web console without hiding the existing chat or activity evidence.
- Keep the feature useful when the model does not explicitly checkpoint.
- Keep the implementation independent from Superpowers source, prompts, names, and branding.

## Non-goals for this slice

- No copied Superpowers skill files or prompt text.
- No automatic subagent dispatch.
- No Git worktree creation or branch management.
- No mandatory human approval gate that would make the existing local chat unusable.
- No new dependency or network service.
- No attempt to infer private chain-of-thought. The workflow stores short operational summaries and evidence, not hidden reasoning.

## Workflow model

The phases are ordered but permit the normal repair loop:

`intake → inspect → design → plan → implement → verify → review → complete`

`blocked` is an exit state reachable from any active phase. `implement → verify → implement` is allowed for a failed check, and `review → implement` is allowed when review finds a problem. Repeating the current phase is always allowed. An explicit checkpoint may move to a later phase or into the repair loop; the harness rejects unknown phases and impossible jumps.

The persisted state is a JSON object with this shape:

```json
{
  "phase": "inspect",
  "status": "active",
  "summary": "The project folder has been inspected.",
  "next_action": "Choose the smallest useful design decision.",
  "artifacts": ["README.md"],
  "checkpoint_count": 1,
  "updated_at": "2026-09-19T12:00:00+00:00"
}
```

`status` is `active`, `complete`, or `blocked`. The event log remains the source of history; `workflow.json` is the current snapshot. Every phase change creates a `workflow_phase` event containing the source (`automatic` or `model`), summary, next action, and state snapshot.

## Checkpoint protocol

The model may emit:

```json
{
  "action": "workflow_checkpoint",
  "args": {
    "phase": "plan",
    "summary": "The implementation is split into a parser, state store, and UI renderer.",
    "next_action": "Write the failing state-transition tests.",
    "artifacts": ["docs/plan.md"]
  }
}
```

The harness validates the phase, strings, artifact path format, and transition. It writes the snapshot under the harness-owned run/session directory, not inside the user's project, and returns the new state to the model. Artifact paths are evidence references only; the existing file tools remain the only way to modify the project.

Automatic evidence mapping is intentionally conservative:

- `list_files` and `read_file` provide inspect evidence.
- `write_file` and `apply_patch` provide implement evidence.
- A successful `run_command` provides verify evidence.
- `git_diff` provides review evidence.
- An accepted `finish` moves the workflow to `complete`; a blocked finish moves it to `blocked`.

Automatic evidence never overwrites a more specific model checkpoint with an unrelated earlier phase. It may advance the active workflow when a successful tool result makes the next phase observable; the only intentional backward movement is the repair loop from `verify` or `review` to `implement` after a new write or patch. Failed tool results do not advance the workflow.

## Integration boundaries

`agent-lab/harness/workflow.py` owns pure state construction, transition validation, automatic evidence mapping, and serialization. It has no HTTP, model, or UI dependencies.

`agent-lab/harness/agent_harness.py` owns protocol registration, checkpoint dispatch, initial snapshot creation, event emission, and run summaries. The existing filesystem and command guards remain unchanged.

`agent-lab/ui/server.py` includes the workflow snapshot in session and run responses. No new endpoint is needed for the first slice because the UI already polls those records.

`agent-lab/ui/index.html`, `agent-lab/ui/app.js`, and `agent-lab/ui/styles.css` add a compact workflow rail in the main workspace and a current phase/next-action detail in the inspector. The visual language remains the existing Agent Lab shell.

## Failure behavior

- Invalid checkpoint input becomes a normal tool error and does not corrupt the previous snapshot.
- A malformed or missing `workflow.json` falls back to a fresh `intake` state while the event log remains readable.
- A filesystem write failure is surfaced as a harness error, not silently swallowed.
- Existing sessions created before this feature are rendered as `intake` until their first new message; loading them does not rewrite their history.
- UI rendering treats absent workflow data as the fallback `intake` state.

## Verification

The feature is complete when unit tests cover valid and invalid transitions, persistence, automatic evidence mapping, and protocol dispatch; Python syntax and the existing harness suite pass; JavaScript syntax passes; and the local UI/API returns a workflow snapshot for both a fresh session and a run record. The reference clone remains outside the Agent Lab project workspaces and is not imported by any runtime code.

