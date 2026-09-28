# Agent Lab Session Rehydration Plan

## Goal

Make interactive conversations genuinely persistent across an Agent Lab UI-server restart. Existing session folders should reappear in the conversation list, preserve visible messages and model context, retain workflow state and project selection, and never remain falsely stuck in `thinking` after the process that owned the worker has exited.

## Design

Use the files Agent Lab already writes rather than introducing a database or a new endpoint:

- `session.json` is the display/session metadata source.
- `transcript.json` is the model conversation context.
- `workflow.json` is the current workflow snapshot, with safe `intake` fallback.
- `config.json` and `workspace.json` restore model settings and project location.

`InteractiveSession.from_disk()` reconstructs a session without calling the new-session `prepare()` path, so it does not erase the run directory or duplicate the original `session_ready` event. Startup scans valid session directories and registers successfully restored sessions. Persisted `busy`/`thinking` state is reset to `busy: false`, because the worker thread cannot survive a server restart. The durable-job layer then marks a persisted in-flight turn as `interrupted` so the user can retry it explicitly, while completed sessions return to `ready`.

## Verification

- Write failing server tests for context restoration, workflow restoration, stale-busy recovery, and startup discovery.
- Run the focused tests and the existing harness suite.
- Restart the real localhost UI server and verify `/api/sessions` exposes old records.
- Open the page and verify a restored conversation renders in the chat, Inspector, and Activity feed.

## Non-goals

This slice does not automatically resume an interrupted model request, reconstruct an old in-memory worker thread, or change the existing project-folder security model. A future message continues from the restored transcript; a request that was mid-flight when the process died must be retried explicitly from the saved job checkpoint.

