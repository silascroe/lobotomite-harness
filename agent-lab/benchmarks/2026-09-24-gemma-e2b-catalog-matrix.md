# Gemma E2B catalog matrix — 2026-09-24

Local `Gemma-4-E2B-Q4_0`, one fresh managed project per run, four catalog tasks at Off, Standard, and Deep. Runs were sequential on one local model server. A pass required harness success **and** the task's external evaluator to pass. This is one sample per cell, not a statistically meaningful ranking of reasoning levels.

| Task | Off | Standard | Deep |
| --- | --- | --- | --- |
| Static page | blocked, 78s, 16/13 calls | blocked, 241s, 18/14 | **pass**, 85s, 9/7 |
| File round-trip | **pass**, 9s, 7/6 | blocked, 54s, 16/11* | blocked, 30s, 9/7 |
| Structured validation | blocked, 14s, 8/8 | blocked, 88s, 18/14 | blocked, 98s, 13/12 |
| Mini project | **pass**, 71s, 16/12 | blocked, 68s, 12/10 | blocked, 210s, 18/15 |

Call counts are model/tool. The full local JSON report contains changed-file lists, evaluator status, validation status, and failure causes: `results/matrix-20260924-003004.json`. Generated projects and logs are under `agent-lab/runs/<run-id>/` and `results/` (both ignored by Git).

The Standard round-trip cell has a grading caveat: the original checker incorrectly rejected a valid numbered checklist. After fixing the checker, that saved artifact passed regrading, and a fresh Standard run passed in 24s. A fresh Deep round-trip run also passed in 18s. These follow-ups are separate runs, not retroactive changes to the original matrix.

Failure modes were mixed: missing/incorrect files, malformed model action JSON, incomplete checkpoint arguments, backward workflow transition, malformed patch syntax, incorrect generated validator behavior, and two 18-turn limits. Deep's static-page pass and Off's mini-project pass show capability, but the 3/12 clean baseline pass rate shows unreliable completion. The structured-validator task had no clean pass. The mini-project checker is structural, not a visual or browser-interaction grade.

The post-matrix recovery-message changes did not turn the Off structured or Standard mini-project spot checks into passes. The harness now accepts an explicit plan checkpoint with a valid summary when only `next_action` is omitted, supplying a neutral next step; unit tests cover that normalization without allowing an absent plan summary. A later Deep round-trip pass did not prove the fallback was exercised. Future work should tackle action-schema reliability and validation repair with another controlled comparison, rather than claiming these messages solved it.
