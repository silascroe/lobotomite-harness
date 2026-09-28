# SDD ledger — plan: docs/superpowers/plans/2026-09-20-durable-interactive-jobs.md

Pre-flight: the existing session lifecycle produces `session.json`, `transcript.json`, and `events.jsonl`; the UI consumes `session.state()`. The new job snapshot must remain in `session.json`, while transcript and events remain the evidence streams.

Task 1: complete — defined `job_state.py` with idle/running/completed/failed/interrupted transitions; 6 job-state tests pass.
Task 2: complete — integrated persisted job snapshots, progress checkpoints, restart interruption, explicit retry, new-message gating, and stale-worker finalization guards; 11 server lifecycle tests pass.
Task 3: complete — exposed `POST /api/sessions/<id>/retry`, added visible recovery copy/button, blocked new messages until recovery, and refreshed UI assets; 20 UI contract assertions pass.
Task 4: complete — full verification passed: 22 harness tests, 11 server lifecycle tests, 20 UI contract assertions, JavaScript syntax, and Python compilation. The localhost UI was restarted and `/api/health` returned `ok`.

