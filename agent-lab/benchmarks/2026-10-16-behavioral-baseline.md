# Gemma E2B baseline on the behavioral checkers — 2026-10-16

Local `Gemma-4-E2B-Q4_0` on the bundled llama.cpp b11045 Vulkan server (`-c 8192`, reasoning budget 1024), all four catalog tasks at Off, Standard and Deep, 18-turn budget, temperature 0.6, fresh managed projects. Three full batches, 36 runs, `matrix-20261016-065825`, `-072523` and `-074931`, run back to back with nothing else using the GPU. The harness is the code at the end of the [2026-10-14 re-grade](2026-10-14-behavioral-regrade.md): the October fixes plus behavioral checkers, evidence strings in the repair reminder, and a 90-second evaluator timeout. No ablation flag is set; this is the reference point later comparisons need.

After the batches, every final project was graded again by the same checkers. All 33 runs that had a recorded evaluation gave the same verdict, so the checkers are repeatable on this set. No run ended on an infrastructure finding or a checker crash.

## Results

| | Off | Standard | Deep | Total |
| --- | --- | --- | --- | --- |
| Static page | 1/3 | 1/3 | 2/3 | **4/9** |
| File round-trip | 3/3 | 3/3 | 3/3 | **9/9** |
| Structured validation | 0/3 | 2/3 | 1/3 | **3/9** |
| Mini project | 2/3 | 2/3 | 1/3 | **5/9** |
| Total | 6/12 | 8/12 | 7/12 | **21/36 (58%)** |

The 95% Wilson interval on 21 of 36 is 42–73%. Reasoning levels do not order (6, 8, 7 of 12), as in the earlier sets.

How the 36 runs ended: 18 passed at the first evaluation; 15 failed it and entered a repair episode, of which 3 passed; 3 never reached an evaluation (one hit the 18-turn limit, one was stopped by a rejected plan checkpoint before inspecting, one lost to a failing `apply_patch`). Mean model calls per run: 14.1.

## Against the October runs

| | Oct 11 set B, as recorded | Oct 11 set B, re-graded | This baseline |
| --- | --- | --- | --- |
| Passed | 26/36 | 18/36 | **21/36** |
| Static page | 3/9 | 2/9 | 4/9 |
| File round-trip | 9/9 | 9/9 | 9/9 |
| Structured validation | 6/9 | 0/9 | 3/9 |
| Mini project | 8/9 | 7/9 | 5/9 |
| First-evaluation passes | 17 | 10 | 18 |
| Repair episodes that passed | 9/15 | 7/15 | 3/15 |

The comparison to the re-graded column is the fair one, because the same checkers judged both. Overall, 21/36 against 18/36 is no difference (Fisher exact p = 0.64), and the per-task differences are small samples (structured validation 3/9 against 0/9, p = 0.21).

Two movements are worth watching but are not established. First-evaluation passes are 18/36 against 10/36 (p = 0.09). The harness changes since October (evidence strings, the longer evaluator timeout) do not touch what a model writes before its first finish, so I have no mechanism for this and treat it as run-to-run variation until a second baseline repeats it. Repair success fell, 3/15 against 7/15 (p = 0.25), which does not support the idea that behavioral evidence in the reminder helps a 2B model, but it does not refute it either; see the next section for why repair had little chance.

## Where the failures came from

15 runs failed. Seven ended on `apply_patch` exhausting its recovery allowance ("could not find update-patch context in the target file"), five used up the six-call repair extension with findings still open, and the last three were a finish rejection for missing review evidence, a rejected plan checkpoint before any inspection, and a turn-limit stop.

Tool failure rates across all 36 runs: `apply_patch` 13 of 31 (42%), `replace_text` 3 of 13, `write_file` 3 of 123 (2.4%), `run_command` 1 of 72, `workflow_checkpoint` 2 of 47. This matches the October pattern: `apply_patch` is the main mechanical failure and `write_file` almost never fails. Repair is hit hardest because a repair is a small edit, which models make with `apply_patch`; of the 12 repair episodes that failed, 6 ended on a patch error. A repair attempt that dies on tooling says little about whether the findings were useful. That is the strongest reason to run the `apply_patch` ablation before drawing conclusions about repair.

Plan-gate friction persists: 28 finish rejections cite the plan phase across the 36 runs.

By task, the failures the behavioral checkers still catch are the same kinds seen in the re-grade. Structured validation misses the name and `generated_for` cases (`validator_rejects_unnamed_check`, `validator_rejects_missing_generated_for`) or fails to accept the valid report. Static page fails on `empty_state`, `count_updates` and crashes on load. Mini project fails on phone width, keyboard activation and status updates.

## Limits

Thirty-six runs, three per cell, temperature 0.6. The interval on the headline is 31 points wide, so only large effects can show up at this size. The three batches ran sequentially on one machine in one afternoon. The comparison with October uses runs from a different time and server session, and the earlier models were shown the old checkers' findings during repair, not behavioral evidence, so repair figures across the two are not like for like. The checkers use fixed test inputs and the first button in `main`, so a page built around a different interaction can be misgraded.

Raw results: `agent-lab/benchmarks/results/matrix-20261016-065825.json`, `-072523.json`, `-074931.json`, with per-run logs and the re-grade at `regrade-20261016-081724.json` (ignored by Git, like other generated results).
