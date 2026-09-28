# Agent harness reference review

Date: 2026-09-21

This project keeps two shallow, read-only reference checkouts beside the
workspace under `.research/agent-reference/`:

- OpenAI Codex: <https://github.com/openai/codex>
- Aider: <https://github.com/Aider-AI/aider>

The directory is ignored by Git and is not on Agent Lab's runtime import path.
Codex is sparse-checked out around its core, agent-role, execution, app-server,
and skill sources because the full repository contains a Windows-incompatible
long snapshot path. Aider checked out normally. Neither repository is vendored,
executed, copied into the harness, or treated as a dependency.

## Patterns used as design research

Codex's source makes the lifecycle of a tool call and turn an explicit event
concern rather than burying it in one opaque model request. Aider's coding loop
feeds concrete lint/test failures back into the next model turn and separates
repository context, command execution, and file editing responsibilities.

Agent Lab already had the beginnings of those ideas: JSONL events, workflow
checkpoints, constrained tools, and a project directory. This pass adds the
missing narrow controller around them: one repair opportunity for a repeated
failure, pre-dispatch duplicate-action detection, durable recovery snapshots,
honest blocked outcomes, and durable tool receipts. A receipt records a tool
call before dispatch, captures its result, and is settled only after the
observation is persisted. Completed receipts can be replayed as observations;
pending receipts are marked unknown and require inspection before another
attempt. The implementation is native Python and retains Agent Lab's own
protocol, gates, and safety rules.

The references are inspiration, not a clone target. If code is ever reused,
license and attribution review must happen first; this slice reuses no upstream
code or prose.

