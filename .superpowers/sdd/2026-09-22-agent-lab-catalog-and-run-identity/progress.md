# SDD ledger — plan: docs/superpowers/plans/2026-09-22-agent-lab-catalog-and-run-identity.md

Pre-flight: Task 1 produces `/api/tasks` entries with `profile`; Task 2 consumes those entries in `start_run()` and persists the selected profile. The interface is explicit and JSON-shaped.

Ruling: The bundled Superpowers shell helpers cannot run because Bash is unavailable on this Windows host; use equivalent PowerShell/apply_patch bookkeeping and preserve the same RED→GREEN and review gates.

Task 1: complete (commit 8532fe0, tests: `node --test agent-lab/ui/test_ui_contract.mjs` → 25/25; `python -m unittest discover -s agent-lab/harness -p 'test_*.py'` → 101/101; `python -m unittest agent-lab/ui/test_server_workflow.py` → 38/38)

Task 2: complete (tests: `node --test agent-lab/ui/test_ui_contract.mjs` → 26/26; `python -m unittest discover -s agent-lab/harness -p 'test_*.py'` → 102/102; `python -m unittest discover -s agent-lab/ui -p 'test_*.py'` → 39/39; `git diff --check` → clean)
