# Agent Lab status

Updated 2026-10-17: new console, and a patch-application finding it surfaced. The 2026-10-16 baseline and first ablation on the behavioral checkers are below. The 2026-10-11 full-project audit ([audit_2026-10-11.md](audit_2026-10-11.md)) is the background for most of this page.

## Current state

The repository contains a working local-first harness with interactive chats and evaluated runs, a browser console, persistent and existing-folder workspaces, structured tool actions, workflow checkpoints, bounded generic recovery, review receipts, resumable run records, independent task evaluators, and an optional OpenAI-compatible provider. The checked-in config selects local Gemma-4-E2B-Q4_0 at reasoning level standard with an 18-turn limit and an 8192-token model window. This describes configuration, not whether a model server is currently running.

The console was redesigned on 2026-10-17 as a flight recorder (see [design-qa.md](../design-qa.md)): a Bench home page of experiments with intervals and per-run matrices, and per-run Recorder, Process, Files, Checks and Log views, with a separate phone layout, replay of any recorded run, chats, and a read-only showcase mode that GitHub Pages serves against sanitized recordings in `site/showcase/` (now the 2026-10-16 behavioral runs). The UI and model launchers use loopback endpoints, and the UI refuses non-loopback `Host`/`Origin` values and non-JSON POSTs, so a web page or a public tunnel cannot drive it. The selected project folder is real host filesystem access, and `run_command` can execute any script the model writes; the harness is not an OS sandbox.

## Verification snapshot

On 2026-10-14 the four Python unittest discovery groups passed: 144 harness, 23 checker (the browser fixtures ran in headless Edge, not skipped), 46 UI-server, and 4 benchmark tests. The Node console suites passed 17 tests (9 contract, 8 narration), and `node --check` passed for every console module. On 2026-10-11 the per-action response schema was smoke-tested against the bundled llama.cpp b11045 server with Gemma E2B, including prompts that explicitly asked for an invalid field and an invalid phase; both were impossible to generate.

## Latest model evidence and its correction

The latest Gemma E2B batch is [2026-10-02](../agent-lab/benchmarks/2026-10-02-gemma-e2b-repair-matrix.md), originally reported as 8 of 12. The audit found that File Round-trip Deep and Structured Validation Deep had finished correctly and pass their checkers when graded afterward; both were stopped by a repeated late `plan` checkpoint that the workflow rejected as a backward transition. Graded on the artifacts, the batch is 10 of 12. The two real failures were Static Page Off (an `apply_patch` action carrying a stray `expected_replacements` field, rejected twice) and Static Page Deep (patch-context failures, then a full-file rewrite cut off when prompt plus reply filled the 8192-token window).

All three harness causes are fixed: repeated late plan checkpoints are harmless notes, the local grammar now constrains each action's arguments, and the local prompt budget leaves room for the reply. Windows file-lock errors that killed two older runs are retried.

The fixes were then measured with three full batches per harness version ([2026-10-11 report](../agent-lab/benchmarks/2026-10-11-gemma-e2b-harness-fixes.md)). With the audit fixes alone, 17 of 36 runs passed. Tracing those failures found three more general problems: evaluator findings vanished from context within a few turns of a repair, patches without the opening marker were fatal, and the duplicate-action refusal gave no next step. With those fixed, 26 of 36 passed (overall p = 0.054), and repair episodes went from 4 of 18 to 9 of 15 successful (p = 0.038). Invalid actions and truncations fell to about zero. Static page remains the weak task (3 of 9), mostly patch-context mismatches.

Those numbers were graded by substring checkers. Re-graded on 2026-10-14 with the behavioral checkers ([report](../agent-lab/benchmarks/2026-10-14-behavioral-regrade.md)), set A stays at 17 of 36 but set B falls from 26 to 18, so the overall A-to-B improvement disappears (p = 1.0). Repairs whose result still works went from 3 of 18 to 7 of 15 (p = 0.13): same direction, no longer significant. Structured validation drops to 0 of 15 because no validator checks names or `generated_for`, and several recorded static-page passes crash on load or reload the page on submit. Every earlier pass rate in this repository should be read as "had the expected markers", not "worked".

The baseline on the new checkers ([2026-10-16 report](../agent-lab/benchmarks/2026-10-16-behavioral-baseline.md)) is 21 of 36 (58%, 95% interval 42-73%): static page 4/9, file round-trip 9/9, structured validation 3/9, mini project 5/9. It is level with set B re-graded (18/36, p = 0.64). 7 of the 15 failures ended on `apply_patch` exhausting recovery, and repair episodes passed 3 of 15, 6 of the 12 failures dying on patch errors, so the repair result says little until `apply_patch` is ablated.

## Known limits

- `apply_patch` accepts a hunk whose context matches nothing when the hunk only adds lines: it inserts the additions at the line number in the `@@` header and reports success. Replaying `apply_update` on recorded inputs confirms it for `matrix-20261016-065825-001-deep` turn 21 (a quoted `<body class="bg-dark">` that never existed put a header line above `<!DOCTYPE html>`; the next patch then failed) and `matrix-20261016-065825-003-deep` turn 10 (a run that still passed after repair). Some recorded "successful" edits are therefore misplaced, so the edit failure rates below are a floor. The console's Files view flags these from the model's last view of the file; whether to reject such hunks is a harness decision not yet made.

- The browser checkers need Node and an installed Edge or Chrome (`AGENT_LAB_BROWSER` overrides the path); without one, browser checks report infrastructure findings and evaluated runs error. They use fixed test inputs and the first button in `main`, so a page built around a different interaction can be misgraded; the finding's evidence string shows what the probe did. Grading a page takes several seconds.
- One baseline of 36 runs exists on the behavioral checkers; the interval is wide, and its first-evaluation pass count (18 vs 10 re-graded for October, p = 0.09) is unexplained and awaits a second baseline.
- "Verify" evidence is any exit-0 command after an edit; in recorded runs it is almost always `node --check`, a syntax check.
- The `plan` gate is still required and was the most common finish rejection (61 times across 78 recorded runs). It mostly costs turns now rather than ending runs.
- Edits to existing files fail about 40% of the time with either edit tool (`apply_patch` 13 of 31, `replace_text` 13 of 29 once `apply_patch` is withheld) against about 2% for `write_file`. The cause is the model working from a wrong picture of the file, not patch syntax, so the [no-`apply_patch` ablation](../agent-lab/benchmarks/2026-10-16-no-apply-patch-ablation.md) changed nothing measurable (22 vs 21 of 36).
- `run_command` allows `python script.py`/`node script.js` for scripts the model writes, so the model can reach the network and any file the user can. `allow_network` in config.json is not enforced by any code. The model could also edit the checkers, which live outside the project but not outside the user's reach.
- The API provider is an experimental provider switch, not evidence that remote-model behavior has been benchmarked comprehensively.
- Path validation, action restrictions, approvals, and workspace leases do not provide OS-level isolation. Avoid secrets and sensitive folders.

## Current repair implementation

The bounded evaluator-guided repair controller follows [the 2026-09-24 specification](superpowers/specs/2026-09-24-agent-lab-evaluator-guided-repair-design.md). It starts only after normal finish gates reach a valid failed evaluator report, grants at most six extra model calls for one episode, persists that allowance across interruption, stops on unchanged findings/project state, and exposes diagnosis/recheck/outcome in events, Inspector and matrix results. Only all existing gates plus a fresh evaluator pass can produce success. Invalid evaluator reports and infrastructure failures end as errors, not model repair attempts.

## Next work

The project is a measuring instrument for how much a harness lifts a tiny model (see the [README](../README.md#why-it-exists)), so work is ordered by whether it makes that measurement trustworthy.

Done first: the substring checkers were replaced with behavioral checks (2026-10-14). A browser probe drives the installed Edge or Chrome over the DevTools protocol with no npm packages; the round-trip module is imported and the validator is run against invalid reports. The baseline matrix on the new checkers is done (2026-10-16), and every ablation compares against it.

Then more ablations on that baseline, several batches per variant with artifacts graded afterward: the `plan` gate on and off, repair on and off, and a bare one-shot baseline with no harness. Removing `apply_patch` is done and showed no effect; the failures suggest trying what the harness shows the model after each edit (the changed region or updated file) before further tool ablations. A strong-model ceiling run through the API provider separates what is the model from what is the harness. Four tasks at three samples per cell is too small to settle any of this; more tasks, more samples, and a second small model are the cheap way to tighten it.

Decide whether `apply_patch` should reject an addition-only hunk whose context matched nothing instead of placing it by line number (see Known limits), and count how often it happened in the recorded batches before the next ablation. Small honesty fixes worth doing alongside: make `allow_network` real or delete it, and correct the system prompt's claim that the model cannot see outside the project. Adding more infrastructure (approvals, receipts, leases) waits until the measurement is trustworthy.
