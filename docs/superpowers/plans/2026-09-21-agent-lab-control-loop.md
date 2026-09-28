# Agent Lab Control Loop Implementation Plan

> Execute this plan in the current worktree. The user explicitly authorized
> autonomous planning, implementation, and verification; do not pause for a
> plan-approval checkpoint. Preserve the pre-existing E2B model-swap changes.

## Scope and constraints

- Runtime code remains independent from `.research/agent-reference/`.
- Use the existing Python `unittest` suites; `pytest` is not a project
  requirement.
- Follow red-green testing for every behavior change.
- Do not weaken `finish_issue()`, workflow gates, path guards, command guards, or
  project isolation.
- Keep the default repair policy to one retry for the same condition.

## Task 1: Add the pure recovery controller

Files:

- Add `agent-lab/harness/control_loop.py`.
- Add `agent-lab/harness/test_control_loop.py`.

Tests first:

1. Canonical argument ordering produces the same fingerprint.
2. A failure gets one `retry` decision, then a `stop` decision.
3. A different failure gets a fresh retry opportunity.
4. A consecutive duplicate action is identified without dispatching it.
5. A different action resets the consecutive duplicate counter.
6. The JSON-safe snapshot round-trips through `from_snapshot()`.

Implement the smallest pure API needed by both loops: `record_failure`,
`observe_action`, `snapshot`, and `from_snapshot`. Validate non-negative limits
and keep persisted data bounded and human-readable.

## Task 2: Integrate benchmark recovery

Files:

- Modify `agent-lab/harness/agent_harness.py`.
- Extend `agent-lab/harness/test_agent_harness.py`.

Tests first:

1. A fake model that emits the same malformed response twice returns blocked
   after the repair opportunity, rather than reaching `max_turns`.
2. A fake model that emits ungated `finish` twice remains blocked and does not
   make the workflow look complete.
3. A duplicate tool action produces a synthetic observation and is not executed
   twice.
4. `summary.json` includes the recovery snapshot and blocked reason.

Integrate the controller at parse, finish, and tool boundaries. Add small
private helpers only where they make event logging and blocked finalization
consistent. Preserve normal success behavior and the current transcript order.

## Task 3: Integrate interactive recovery and persistence

Files:

- Modify `agent-lab/ui/server.py`.
- Extend `agent-lab/ui/test_server_workflow.py`.

Tests first:

1. A duplicate action is observed as a recovery result without a second call to
   the underlying tool dispatcher.
2. An exhausted recovery condition adds a visible assistant message and ends
   the current job cleanly.
3. `save_meta()` writes recovery state and `from_disk()` restores it.

Use the same controller object already owned by `AgentHarness`; do not create a
second policy in the server. Keep startup behavior explicit: interrupted jobs
still require user retry and are never auto-resumed.

## Task 4: Durable API/summary surface and documentation

Files:

- Modify `agent-lab/README.md` if the final behavior needs operator guidance.
- Modify `agent-lab/harness/config.json` only if an explicit recovery policy
  setting is useful; defaults must work without configuration.
- Update the SDD ledger with the chosen defaults and evidence.

Expose recovery in existing run/session state payloads through the persisted
summary/session metadata. Avoid a speculative UI rewrite; add UI work only if a
contract test proves the current surface hides the new state.

## Task 5: Verification and model smoke test

Run, in order:

1. Focused controller tests.
2. Focused harness and server tests.
3. Full harness and UI `unittest` discovery suites.
4. JavaScript contract tests and Python compilation.
5. `git diff --check` and a self-review of the diff.
6. One gated E2B benchmark with the existing model server. Compare its stop
   reason and call count with the earlier run; do not change gates to improve
   the result.

Record exact commands and outcomes in the ledger. Stop engineering when the
controller, both loops, persistence, and verification are complete; do not add
unrelated model tuning or another UI redesign in this pass.

