# Durable interactive jobs

## Goal

Make an interactive Agent Lab turn honest and recoverable when the Python process disappears. A completed conversation remains usable, but an in-flight model/tool turn must reopen as `interrupted`, never retry by itself, and offer an explicit user-controlled retry from the persisted transcript.

## Scope

- Persist one current job record inside each interactive session's `session.json`.
- Treat a persisted `running` job, or a legacy busy session whose last visible message is a user message, as interrupted during rehydration.
- Persist observable progress after model responses and tool results so retry can continue from the latest saved transcript instead of blindly repeating a known tool call.
- Add explicit retry/resume API and UI affordances. A retry creates a new attempt; it never starts automatically.
- Guard worker finalization with a job identifier so an old thread cannot overwrite a newer attempt.
- Keep benchmark/run subprocess behavior unchanged in this slice.

## Job contract

`session.json` gains a `job` object with `job_id`, `status`, `attempt`, `user_message`, timestamps, `current_step`, `last_action`, and `error`. Statuses are `idle`, `running`, `completed`, `failed`, and `interrupted`.

The public session status remains `thinking` only while a live worker is running. Rehydrated interrupted work has `busy: false`, `status: interrupted`, and a visible recovery action. Explicit retry changes the job to `running`, increments `attempt`, and reuses the persisted user message without appending a duplicate public message.

## Safety rules

- Never auto-retry on startup.
- Persist transcript and job progress after each model response and tool result.
- If a process disappears after a tool may have run, the next attempt receives the saved observation and must inspect before acting again.
- A stale worker may finish only if its `job_id` is still current.
- Retry is allowed only for `interrupted` or `failed` jobs and is initiated by the user.

## Verification

- Unit tests cover job normalization/transitions, interrupted rehydration, explicit retry without duplicate user messages, progress persistence, and stale-worker finalization.
- Server/UI contract tests cover the retry endpoint, visible recovery control, interrupted status copy, and the no-auto-retry rule.
- Existing harness/server tests, Python compilation, JavaScript syntax, and the UI contract suite remain green.

