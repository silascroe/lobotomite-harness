# Ablation: withhold `apply_patch` — 2026-10-16

Question: `apply_patch` failed 42% of the time in the [baseline](2026-10-16-behavioral-baseline.md) and ended 7 of its 15 failed runs. If the small model cannot use it, leaving only `write_file` and `replace_text`, does it do better?

Method: the baseline's design with one change. `apply_patch` is removed from the prompt, from the grammar schema the local server constrains output with, and from action validation (`disabled_actions` in config, `--disable-action` on the harness and matrix runner). Gemma E2B on the same server and settings, four tasks at Off, Standard and Deep, three batches (36 runs): `matrix-20261016-164642`, `-170630`, `-172837`, all with the behavioral checkers. The baseline batches ran earlier the same day. No run emitted `apply_patch` or had an action rejected as unknown, so the model never saw the action and the withholding worked.

## Result

| | Baseline | No `apply_patch` |
| --- | --- | --- |
| Passed | 21/36 (58%) | **22/36 (61%)** |
| Static page | 4/9 | 4/9 |
| File round-trip | 9/9 | 9/9 |
| Structured validation | 3/9 | 2/9 |
| Mini project | 5/9 | 7/9 |
| First-evaluation passes | 18 | 19 |
| Repair episodes that passed | 3/15 | 3/15 |
| Never reached an evaluation | 3 | 2 |
| Mean model calls / seconds per run | 14.1 / 129 | 13.2 / 109 |

Withholding `apply_patch` made no measurable difference to the pass rate (22 vs 21, Fisher exact p = 1.0). The one visible per-task movement, mini project 7/9 against 5/9, is two runs (p = 0.62) and is not evidence of anything. Repair did not improve: 3 of 15 in both.

## Why nothing changed

The failures moved to the tool that replaced it. `replace_text` failed 13 of 29 times (45%), where `apply_patch` failed 13 of 31 (42%) in the baseline; `write_file` failed 4 of 133. Counting both edit tools, the baseline failed 16 of 44 edits to existing files and the variant 13 of 29. The causes are the same kind of mistake:

- Baseline `apply_patch`: 12 "could not find update-patch context in the target file".
- Variant `replace_text`: 6 "would not change the file" (the replacement equals the original text), 4 "expected 1 exact replacements, found 0", and 3 duplicate-action refusals.

In both cases the model is editing against a file it misremembers: text it already changed, or text it never read closely. That is a limit of the model's tracking of file state, not of the patch syntax. The ablation removed the syntax problem (no more "patch must start with *** Begin Patch") and left this one standing.

How the 14 failed runs ended, against the baseline's: 5 `replace_text` failures after retry (baseline: 7 `apply_patch`), 5 duplicate-action stops (baseline: 0), 2 exhausted repair extensions (baseline: 5), 1 model-declared blocked and 1 rejected workflow transition. The duplicate-action stops are new: with no patch tool, a model that cannot make its edit sometimes resends the same `write_file` or `replace_text` call, and the duplicate guard ends the run. These are mostly structured-validation and static-page repairs.

## What this does and does not show

It shows that `apply_patch` is not the cause of the baseline's failures in any way that removing it fixes; the harness should not drop it on this evidence. It does not show `apply_patch` helps, either: the pass rates are the same, and the variant finished slightly faster (109 s against 129 s per run, one batch of runs each, no test).

The comparison has the baseline's limits plus one: the two sets ran hours apart on the same machine, not interleaved. With 36 runs per arm the test can only reveal a difference of roughly 25 percentage points, so an effect of 10 points either way is invisible. A repeated baseline and variant batch would tighten that.

An untested idea the failures suggest: the model's errors come from a wrong picture of the file, so what the harness shows it after each edit (the changed region, or the updated file) may matter more than which edit tool exists. That would be the next harness change to measure, ahead of further tool ablations.

Raw results: `agent-lab/benchmarks/results/matrix-20261016-164642.json`, `-170630.json`, `-172837.json` (each records `"variant": "no-apply-patch"`), log `ablation-no-apply-patch-20261016.log` (ignored by Git).
