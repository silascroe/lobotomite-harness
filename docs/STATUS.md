# Agent Lab status

Updated 2026-10-02 from the current local implementation and recorded benchmark evidence.

## Current state

The repository contains a working local-first harness with interactive chats and evaluated runs, a browser console, persistent and existing-folder workspaces, structured tool actions, workflow checkpoints, bounded generic recovery, review receipts, resumable run records, independent task evaluators, and an optional OpenAI-compatible provider. The checked-in config selects local Gemma-4-E2B-Q4_0 at reasoning level standard with an 18-turn limit. This describes configuration, not whether a model server is currently running.

The UI and model launchers use loopback endpoints. The selected project folder is real host filesystem access; the harness is not an OS sandbox.

## Verification snapshot

On 2026-10-02, the four Python unittest discovery groups passed: 132 harness, 6 checker, 40 UI-server, and 4 benchmark tests. The Node UI contract suite passed 27 checks, and node --check agent-lab/ui/app.js passed. These include deterministic repair, fresh finish gates, approvals, no-progress stops, six-call exhaustion, persisted/resumed allowance, evaluator errors, API response preservation and first-pass/repaired metrics.

The latest Gemma E2B catalog batch is [2026-10-02](../agent-lab/benchmarks/2026-10-02-gemma-e2b-repair-matrix.md): 8 of 12 runs passed, including 6 first-evaluation passes and 2 repaired passes (Mini Project Off and Deep). Four repair episodes started; two passed and two stopped on generic recovery limits. One failed episode used four extra calls. No run exceeded the 24-call ceiling. This is one sample per cell and integration evidence, not a pinned-revision comparison or a reliable ranking of reasoning levels. The mini-project checker is structural, not a visual/browser-quality grade. The earlier [September measurements](../agent-lab/benchmarks/2026-09-24-gemma-e2b-catalog-matrix.md) remain historical evidence.

## Known limits

- Evaluator-guided repair is implemented, but a model can still fail a checker or misuse tools during its bounded episode. It is not an automatic fix or a guaranteed capability gain.
- The latest matrix shows uneven results: Structured Validation Off and Mini Project Off exposed different failure modes; action correctness alone did not guarantee task quality or completion efficiency.
- The API provider is an experimental provider switch, not evidence that remote-model behavior has been benchmarked comprehensively.
- Path validation, action restrictions, approvals, and workspace leases do not provide OS-level isolation. Avoid secrets and sensitive folders.

## Current repair implementation

The bounded evaluator-guided repair controller follows [the 2026-09-24 specification](superpowers/specs/2026-09-24-agent-lab-evaluator-guided-repair-design.md). It starts only after normal finish gates reach a valid failed evaluator report, grants at most six extra model calls for one episode, persists that allowance across interruption, stops on unchanged findings/project state, and exposes diagnosis/recheck/outcome in events, Inspector and matrix results. Only all existing gates plus a fresh evaluator pass can produce success. Invalid evaluator reports and infrastructure failures end as errors, not model repair attempts.

The 12-cell batch `matrix-20261002-072910` is complete. The next meaningful question is whether repeated fresh batches reproduce the repaired passes and whether targeted guidance can reduce the remaining malformed patch and late-workflow failures without weakening existing limits. Do not infer a general capability gain from this one batch.
