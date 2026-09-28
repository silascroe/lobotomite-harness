# Agent Lab Control Loop Design

## Intent

Make Agent Lab's harness behave like a durable controller around a small local
model rather than a prompt wrapped around a turn counter. The model remains the
planner and tool user, but the harness owns bounded recovery, duplicate-action
detection, durable attempt state, and honest stopping.

This is an independent Agent Lab design. The local Codex and Aider checkouts in
`.research/agent-reference/` are read-only research material and are not runtime
dependencies. Their useful patterns are event-shaped task state, explicit tool
lifecycle records, and feeding lint/test failures back into the next model turn.

## Problem

The current benchmark loop and interactive loop each implement their own loose
retry behavior. A malformed response, rejected finish, or failed tool produces a
correction, but the same correction can be emitted repeatedly until the global
turn limit. A model can also repeat the same tool call after receiving its
result. The result is expensive, opaque, and especially punishing for E2B-sized
models: a run can spend most of its budget proving that it is stuck.

The existing workflow gates are valuable evidence checks. They must not be
weakened to make a model look better, and a controller must never fabricate a
plan, validation result, or successful finish.

## Goals

- Use one small, pure recovery controller in benchmark and interactive loops.
- Give each repeated protocol, gate, or tool failure one targeted repair turn.
- Detect consecutive duplicate tool actions before dispatching the duplicate.
- Stop a benchmark honestly as `blocked` when the same failure survives its
  repair opportunity.
- Turn the equivalent interactive condition into a visible assistant recovery
  message while keeping the session usable for a later user message.
- Persist recovery counters and the last action in run summaries and interactive
  session metadata so a restart does not erase the explanation.
- Emit compact recovery events that make the decision inspectable in the UI and
  in `events.jsonl`.
- Keep tool guards, workflow gates, project isolation, and the current JSON
  protocol unchanged.

## Non-goals

- No copied Codex or Aider code, prompts, branding, or dependencies.
- No automatic retry of an unavailable model endpoint; infrastructure failures
  remain explicit harness errors for now.
- No automatic retry of an interrupted interactive job on server startup.
- No automatic approval of tools, commands, workflow checkpoints, or finish
  claims.
- No broad redesign of the UI in this slice; the existing activity/event surface
  already has a place to expose the new events, and the API will include the
  durable snapshot.

## Chosen design

### Recovery controller

Add `agent-lab/harness/control_loop.py` with a dependency-free
`RecoveryController` and immutable `RecoveryDecision` value. The controller
tracks:

- failure attempts keyed by a normalized category and detail;
- the last dispatched-or-attempted action fingerprint;
- the consecutive repeat count for that fingerprint;
- the configured one-repair limit and duplicate-action limit.

Action fingerprints are stable hashes of the action name and canonical JSON
arguments. Argument key order must not change the fingerprint. Failure details
are whitespace-normalized and clipped before being keyed so a model cannot
create unbounded persistence by adding prose to an otherwise identical error.

The default policy is one retry for the same failure and one corrective turn for
the same consecutive action. The first occurrence returns a `retry` decision;
the next occurrence returns a `stop` decision. A different action or different
failure key receives its own single repair opportunity. The controller is pure
state and policy: callers decide what message to send, what event to log, and
whether a stop means blocked or an interactive assistant notice.

### Benchmark loop

`AgentHarness.run()` will use the controller at three boundaries:

1. Invalid JSON/action protocol: retry once with a precise repair instruction,
   then mark the run blocked with the original failure and attempted turn.
2. Rejected `finish`: retry once with the real missing evidence, then block;
   gates remain authoritative.
3. Tool failures and repeated actions: provide one observation/correction, block
   on the repeated failure, and never dispatch the same consecutive action after
   the controller identifies it as a duplicate.

The run summary will include a `recovery` snapshot and a `blocked_reason` when
the controller stops the run. A successful finish still passes through all
existing `finish_issue()` checks.

If a model supplies an explicit `plan` checkpoint after automatic evidence has
already advanced the visible phase to `implement`, `verify`, or `review`, the
harness records the plan as late evidence without rewinding the visible phase.
The event is named `workflow_late_evidence`, and the response marks `late: true`.
This keeps the ordering visible while avoiding a brittle dead end where a
truthful operational plan cannot be recorded merely because implementation
started too early.

### Interactive loop

`InteractiveSession.process()` will use the same controller and policy. A
recoverable condition is added to the model transcript as a targeted
observation. An exhausted condition produces a concise assistant message such
as “I stopped after one repair attempt because …” and ends only the current
message job; it does not poison the whole session. The persisted job remains
completed, the session returns to ready, and the user can send a new message or
use the existing retry action for an interrupted worker.

The controller snapshot is written in `session.json` whenever the current job
progress is saved and restored by `InteractiveSession.from_disk()`.

### Evidence and persistence

Recovery events use these event names:

- `recovery_retry`: a repair turn was granted;
- `recovery_duplicate_action`: a duplicate was blocked before tool dispatch;
- `recovery_exhausted`: the same condition reached its limit;

Each event includes category, detail, attempt, limit, turn/step, and the
controller snapshot. The snapshot is operational state only; it contains no
hidden reasoning.

## Alternatives rejected

Increasing `max_turns` is not recovery. It gives a stuck model more rope and
does not tell the user why it stopped. Prompt-only instructions are cheaper to
write but cannot reliably distinguish a repeated action or persist the decision.
Automatically faking missing workflow checkpoints would make benchmark scores
meaningless. A full event-sourced state machine would be disproportionate here;
the existing JSONL event log plus a small persisted controller snapshot gives
the needed durability without another database.

## Verification

- Unit tests for canonical action fingerprints, one-retry-then-stop failure
  decisions, duplicate-action decisions, and snapshot round trips.
- Harness tests proving repeated invalid output and repeated finish rejection
  stop early without accepting an ungated success.
- Interactive server tests proving a duplicate tool action is not dispatched
  twice and that recovery state survives metadata restoration.
- Full harness and UI Python suites, JavaScript contract tests, syntax checks,
  and `git diff --check`.
- One real gated E2B run to confirm a stuck model stops with a useful blocked
  reason rather than burning the entire turn budget; no gate weakening is
  allowed if that run still fails.

