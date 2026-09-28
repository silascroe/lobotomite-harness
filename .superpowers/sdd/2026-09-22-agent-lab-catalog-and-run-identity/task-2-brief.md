# Task 2: Apply task profiles and persist run identity

Add `--task-profile-json` and `apply_task_profile(config, profile)` to the harness. The server must validate preset names, pass the selected profile to the worker, and expose persisted `task_profile` metadata. The UI must send `task_name`, show the preset title in run records, and fall back for historical/custom records.

Required tests:
- `C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest agent-lab/harness/test_agent_harness.py agent-lab/ui/test_server_workflow.py`
- `node --test agent-lab/ui/test_ui_contract.mjs`
- `C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s agent-lab/harness -p 'test_*.py'`

Commit: `Make Agent Lab runs task-aware`.

