# File round-trip smoke test

Exercise the harness's core file and validation loop in the current project. This is intentionally small and should finish quickly.

First inspect the project with `list_files`. Record a short plan with `workflow_checkpoint` before making changes. Then create both files below:

- `agent-check.md`: a short note with a title, the purpose of this smoke test, and three checklist items.
- `agent-check.mjs`: a tiny valid JavaScript module that exports a constant named `status` with the value `"ok"`.

Read both files back with `read_file` after writing them. Verify the JavaScript with the local command `node --check agent-check.mjs`; do not install packages or use the network. Review the complete change with `git_diff`, then call `finish` with an honest summary of the files and validation result.

