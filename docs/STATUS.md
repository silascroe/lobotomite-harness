# Agent Lab status

Updated 2026-10-11 after a full-project audit ([audit_2026-10-11.md](audit_2026-10-11.md)) and the fixes it led to.

## Current state

The repository contains a working local-first harness with interactive chats and evaluated runs, a browser console, persistent and existing-folder workspaces, structured tool actions, workflow checkpoints, bounded generic recovery, review receipts, resumable run records, independent task evaluators, and an optional OpenAI-compatible provider. The checked-in config selects local Gemma-4-E2B-Q4_0 at reasoning level standard with an 18-turn limit and an 8192-token model window. This describes configuration, not whether a model server is currently running.

The console was rebuilt from scratch on 2026-10-11 (see [design-qa.md](../design-qa.md)): live narration of tool calls, an animated specimen for agent state, a verdict-first run page, replay of any recorded run, chats with folded per-reply work, and a read-only showcase mode that GitHub Pages serves against sanitized recordings in `site/showcase/`. The UI and model launchers use loopback endpoints, and the UI refuses non-loopback `Host`/`Origin` values and non-JSON POSTs, so a web page or a public tunnel cannot drive it. The selected project folder is real host filesystem access, and `run_command` can execute any script the model writes; the harness is not an OS sandbox.

## Verification snapshot

On 2026-10-11 the four Python unittest discovery groups passed: 143 harness, 6 checker, 46 UI-server, and 4 benchmark tests. The Node console suites passed 17 tests (9 contract, 8 narration), and `node --check` passed for every console module. The per-action response schema was smoke-tested against the bundled llama.cpp b11045 server with Gemma E2B, including prompts that explicitly asked for an invalid field and an invalid phase; both were impossible to generate.

## Latest model evidence and its correction

The latest Gemma E2B batch is [2026-10-02](../agent-lab/benchmarks/2026-10-02-gemma-e2b-repair-matrix.md), originally reported as 8 of 12. The audit found that File Round-trip Deep and Structured Validation Deep had finished correctly and pass their checkers when graded afterward; both were stopped by a repeated late `plan` checkpoint that the workflow rejected as a backward transition. Graded on the artifacts, the batch is 10 of 12. The two real failures were Static Page Off (an `apply_patch` action carrying a stray `expected_replacements` field, rejected twice) and Static Page Deep (patch-context failures, then a full-file rewrite cut off when prompt plus reply filled the 8192-token window).

All three harness causes are fixed: repeated late plan checkpoints are harmless notes, the local grammar now constrains each action's arguments, and the local prompt budget leaves room for the reply. Windows file-lock errors that killed two older runs are retried.

The fixes were then measured with three full batches per harness version ([2026-10-11 report](../agent-lab/benchmarks/2026-10-11-gemma-e2b-harness-fixes.md)). With the audit fixes alone, 17 of 36 runs passed. Tracing those failures found three more general problems: evaluator findings vanished from context within a few turns of a repair, patches without the opening marker were fatal, and the duplicate-action refusal gave no next step. With those fixed, 26 of 36 passed (overall p = 0.054), and repair episodes went from 4 of 18 to 9 of 15 successful (p = 0.038). Invalid actions and truncations fell to about zero. Static page remains the weak task (3 of 9), mostly patch-context mismatches.

## Known limits

- The checkers are structural substring tests (for example `:focus` appearing in CSS), not behavioral tests. They can pass a broken page and fail a working one, so pass rates measure form more than function.
- "Verify" evidence is any exit-0 command after an edit; in recorded runs it is almost always `node --check`, a syntax check.
- The `plan` gate is still required and was the most common finish rejection (61 times across 78 recorded runs). It mostly costs turns now rather than ending runs.
- `apply_patch` failed 64% of the time in older runs and still 35% after the fixes, against about 2% for `write_file`; it is the main remaining mechanical failure, concentrated in the static page task.
- `run_command` allows `python script.py`/`node script.js` for scripts the model writes, so the model can reach the network and any file the user can. `allow_network` in config.json is not enforced by any code. The model could also edit the checkers, which live outside the project but not outside the user's reach.
- The API provider is an experimental provider switch, not evidence that remote-model behavior has been benchmarked comprehensively.
- Path validation, action restrictions, approvals, and workspace leases do not provide OS-level isolation. Avoid secrets and sensitive folders.

## Current repair implementation

The bounded evaluator-guided repair controller follows [the 2026-09-24 specification](superpowers/specs/2026-09-24-agent-lab-evaluator-guided-repair-design.md). It starts only after normal finish gates reach a valid failed evaluator report, grants at most six extra model calls for one episode, persists that allowance across interruption, stops on unchanged findings/project state, and exposes diagnosis/recheck/outcome in events, Inspector and matrix results. Only all existing gates plus a fresh evaluator pass can produce success. Invalid evaluator reports and infrastructure failures end as errors, not model repair attempts.

## Next work

Replace the substring checkers with behavioral checks (load the page, submit the form, count the cards) so that a pass means the thing works; that is also the precondition for a meaningful strong-model comparison through the API provider. After that, test whether removing `apply_patch` from the small-model action set (leaving `replace_text` and `write_file`) helps the static page task, measured the same way: several batches per variant, artifacts graded afterward.
