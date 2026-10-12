# Gemma E2B evaluator-guided repair matrix — 2026-10-02

Batch: `matrix-20261002-072910`. Local `Gemma-4-E2B-Q4_0` on the existing llama.cpp b11045 Vulkan server, four catalog tasks at Off, Standard and Deep, sequentially in fresh managed projects. Normal budget: 18 turns; one repair episode may reserve at most six extra model calls. No API provider was used. Runtime summed to 1,009 seconds (about 17 minutes).

## Results

Eight of twelve runs passed: six first-evaluation passes and two repaired passes. Four episodes started; two passed and two stopped under the existing generic recovery policy. Two runs stopped before obtaining a valid evaluator result, so their first-pass values are null, not false. Only Static Page Deep used extension calls: four, before a repeated patch-context failure stopped it. No run exceeded 24 model calls; the maximum observed was 22.

| Task | Reasoning | First evaluation | Final result | Model/tool calls | Repair outcome | Extra calls |
| --- | --- | --- | --- | --- | --- | --- |
| Static page | Off | Failed | Blocked | 12/8 | Blocked | 0 |
| Static page | Standard | Passed | Passed | 9/7 | Not attempted | 0 |
| Static page | Deep | Failed | Blocked | 22/19 | Blocked | 4 |
| File round-trip | Off | Passed | Passed | 7/6 | Not attempted | 0 |
| File round-trip | Standard | Passed | Passed | 9/7 | Not attempted | 0 |
| File round-trip | Deep | Not reached | Blocked | 10/9 | Not attempted | 0 |
| Structured validation | Off | Passed | Passed | 7/6 | Not attempted | 0 |
| Structured validation | Standard | Passed | Passed | 13/11 | Not attempted | 0 |
| Structured validation | Deep | Not reached | Blocked | 9/8 | Not attempted | 0 |
| Mini project | Off | Failed | Passed | 13/11 | Passed | 0 |
| Mini project | Standard | Passed | Passed | 9/7 | Not attempted | 0 |
| Mini project | Deep | Failed | Passed | 15/12 | Passed | 0 |

Mini Project Off initially failed `focus_style` and `responsive_css`. The model edited its project, reran validation and reviewed the new diff; a fresh checker pass removed both findings. Its episode used six model turns including the triggering finish. Mini Project Deep repaired `focus_style` in seven episode turns including the trigger. Both repairs completed inside the normal 18-turn budget, so neither needed extension calls.

Static Page Off stopped on repeated malformed `apply_patch` arguments (`expected_replacements` is not a supported patch argument), retaining four failed requirements. Static Page Deep stopped after repeated patch-context failures, retaining `has_focus_style`. File Round-trip Deep and Structured Validation Deep stopped on repeated late `review -> plan` workflow transition errors before evaluation. These are genuine remaining model/harness interaction limits; this implementation did not relax their gates to turn them green.

## Verification and limits

The final local regression suites pass: 132 harness tests, 6 checker tests, 40 UI-server tests, 4 benchmark tests and 27 Node UI contracts; JavaScript syntax and Git whitespace checks also pass. Deterministic tests cover unchanged-project stops, hard extension exhaustion, interrupted-state restoration, spent extension on resume, fresh validation/review after edits, approval pauses, generic recovery within repair, invalid evaluator reports, evaluator timeout, and missing-Node infrastructure classification.

This is one sample per task/reasoning cell, not a reliable reasoning-level ranking or a proven improvement over the [September measurements](2026-09-24-gemma-e2b-catalog-matrix.md). Snapshot validation, progress-display and reporting hardening continued while this batch ran; it is end-to-end integration evidence, not a pinned-revision comparative experiment. The tasks, provider configuration and grading checks were not retuned. The mini-project checker remains structural, not a visual-quality assessment. Resume/no-progress/exhaustion coverage is deterministic test evidence, not a claim those paths all occurred in this model batch.

The detailed local JSON is `results/matrix-20261002-072910.json`; individual runs live at `agent-lab/runs/matrix-20261002-072910-<task-number>-<level>/`. Generated JSON, transcripts and model outputs remain ignored by Git. Each episode's canonical state is `repair.json`; progress, summary and events carry its inspection view. The local Gemma server was started for this batch and left running for further use.

## Correction (2026-10-11)

Two of the four failures were not model failures. File Round-trip Deep and Structured Validation Deep completed their tasks, validated and reviewed them, then sent a second late `plan` checkpoint; the workflow rejected it as `review -> plan`, the repeat exhausted recovery, and the runs stopped before evaluation. Running the checkers on those projects afterward passes every check, so graded on the artifacts the batch is **10 of 12**, and the apparent weakness of Deep in this table is mostly this bug. Static Page Deep's final failure was the 8192-token llama.cpp window filling (prompt 6,638 + reply 1,554 tokens), not the output cap. The harness causes were fixed on 2026-10-11 (see [STATUS](../../docs/STATUS.md) and the [audit](../../docs/audit_2026-10-11.md)); the table above is left as recorded.
