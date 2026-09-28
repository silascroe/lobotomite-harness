# Task 1: Add the curated built-in run catalog

Add four built-in task presets: the existing static-page benchmark plus file round-trip, structured validation, and mini-project smoke tests. Store task-specific gate profiles in `agent-lab/tasks/catalog.json`, load them from `task_catalog()`, document them, and cover the catalog with the UI contract test. The new profiles must not inherit the old static-page evaluator.

Required tests:
- `node --test agent-lab/ui/test_ui_contract.mjs`
- `C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s agent-lab/harness -p 'test_*.py'`

Commit: `Add curated Agent Lab run catalog`.

