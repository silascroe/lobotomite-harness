# Gemma E2B after the audit fixes — 2026-10-11

> Graded by the old substring checkers. Re-graded with behavioral checkers on 2026-10-14, set B falls from 26 to 18 of 36 and the overall improvement over set A disappears; see [the re-grade](2026-10-14-behavioral-regrade.md).

Local `Gemma-4-E2B-Q4_0` on the bundled llama.cpp b11045 Vulkan server (`-c 8192`), the four catalog tasks at Off, Standard and Deep, 18-turn budget, temperature 0.6, fresh managed projects. Each set is three full batches (36 runs), so every cell has three samples instead of one. Every project was also graded afterward by its checker, to separate "the work was wrong" from "the harness stopped correct work".

## Sets

**A, audit fixes** (`matrix-20261011-185251`, `-192057`, `-194103`): loopback-only console, harmless repeated late `plan` checkpoints, per-action grammar schema, prompt budget that fits the 8192-token window, truncation-specific correction, Windows rename retry.

**B, corrected** (`matrix-20261011-201925`, `-203757`, `-205901`): A plus three fixes found by tracing A's failures. Open evaluator findings are repeated on every repair request with a status derived from the project fingerprint and fresh evidence (edit, validate, review, or call finish now); `apply_patch` accepts a patch that starts at a valid file header; the duplicate-action refusal names the next workflow step.

An intermediate version repeated the findings without the status line. Its one completed batch (`matrix-20261011-195859`) passed 5 of 12 while 9 of 12 projects were correct: the static reminder kept saying "edit these files" after the fix had succeeded, the model repeated successful patches or validation, and the duplicate guard ended the runs. It was stopped mid-way (`matrix-20261011-201750-001-off` is an interrupted partial run) and is excluded from both sets.

## Results

| | Set A | Set B |
| --- | --- | --- |
| Passed | 17/36 (47%) | **26/36 (72%)** |
| First-evaluation passes | 13 | 17 |
| Repaired passes | 4 | 9 |
| Repair episodes that passed | 4/18 (22%) | **9/15 (60%)** |
| Projects passing their checker afterward | 20 | 28 |
| Mean model calls per run | 14.4 | 13.0 |

| Task | Set A | Set B |
| --- | --- | --- |
| Static page | 2/9 | 3/9 |
| File round-trip | 9/9 | 9/9 |
| Structured validation | 2/9 | 6/9 |
| Mini project | 4/9 | 8/9 |

Fisher exact tests (two-sided): repair success 4/18 vs 9/15, p = 0.038; overall pass rate 17/36 vs 26/36, p = 0.054; first-evaluation passes 13/36 vs 17/36, p = 0.47. The repair improvement is the change set B targeted and is the best-supported effect. The overall gain is suggestive but borderline, and part of it is first-pass variation that set B's changes barely touch. Reasoning levels do not order consistently (A: Off 5, Standard 4, Deep 8 of 12; B: 9, 9, 8), so no ranking of levels is supported.

In set A's 517 model responses and set B's 467, there were 0 and 1 invalid actions (historically 31 in 849) and 0 and 1 truncations (historically 18); no harness errors occurred. `apply_patch` failed 18 of 27 times in A and 9 of 26 in B, against 2 of 118 for `write_file` in B.

## Remaining failures in set B

Static page accounts for six of ten: three patch-context mismatches (the patch's context lines do not match the file), two turn-limit stops, and one plan checkpoint sent before any inspection. Structured validation lost three, to a `require`/`import` mix-up the model reported as an environment problem, a `replace_text` whose `old_text` was not in the file, and an exhausted repair. Mini project Deep fixed `responsive_css` on its final turn without calling finish. These read as model capability limits plus `apply_patch` being a poor fit for a 2B model, not as harness defects.

## Limits

Three samples per cell at temperature 0.6 is still small. The checkers are structural substring tests, so a pass means the expected markers are present, not that the page behaves correctly. Sets A and B ran back to back on the same machine and server and differ only in the harness code described above.
