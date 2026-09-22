# SDD ledger — plan: docs/superpowers/plans/2026-09-22-agent-lab-catalog-and-run-identity.md

Pre-flight: Task 1 produces `/api/tasks` entries with `profile`; Task 2 consumes those entries in `start_run()` and persists the selected profile. The interface is explicit and JSON-shaped.

Ruling: The bundled Superpowers shell helpers cannot run because Bash is unavailable on this Windows host; use equivalent PowerShell/apply_patch bookkeeping and preserve the same RED→GREEN and review gates.
