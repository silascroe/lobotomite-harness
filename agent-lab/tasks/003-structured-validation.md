# Structured validation smoke test

Build a tiny, inspectable health-report artifact without using dependencies or the network.

Start by inspecting the project with `list_files`, then record a short plan with `workflow_checkpoint`. Create:

- `health-report.json`: valid JSON containing a top-level `status` equal to `"ok"`, a `checks` array with at least two named checks, and a short `generated_for` string.
- `validate-report.mjs`: a dependency-free Node script that reads `health-report.json`, checks those fields, prints a concise success message, and exits nonzero when the shape is invalid.

Read the created files back, run `node validate-report.mjs` as the local validation command, and use `git_diff` to review the complete change after validation. Then call `finish` with an honest summary. Do not install packages or fetch anything.

