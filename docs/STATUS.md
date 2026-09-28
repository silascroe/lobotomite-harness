# Agent Lab status

Updated 2026-09-27 from the checked-in implementation and recorded benchmark evidence.

## Current state

The repository contains a working local-first harness with interactive chats and evaluated runs, a browser console, persistent and existing-folder workspaces, structured tool actions, workflow checkpoints, bounded generic recovery, review receipts, resumable run records, independent task evaluators, and an optional OpenAI-compatible provider. The checked-in config selects local Gemma-4-E2B-Q4_0 at reasoning level standard with an 18-turn limit. This describes configuration, not whether a model server is currently running.

The UI and model launchers use loopback endpoints. The selected project folder is real host filesystem access; the harness is not an OS sandbox.

## Verification snapshot

On 2026-09-27, the four Python unittest discovery groups passed: 112 harness, 4 checker, 39 UI-server, and 2 benchmark tests. The Node UI contract suite passed 26 checks, and node --check agent-lab/ui/app.js passed.

The latest recorded uniform Gemma E2B catalog matrix is [2026-09-24](../agent-lab/benchmarks/2026-09-24-gemma-e2b-catalog-matrix.md): 6 of 12 cells passed in that batch. Separate follow-up runs raised the number of task/level cells with at least one passing run to 7 of 12. This is a small experimental sample, not a reliable ranking of reasoning levels. The mini-project checker is structural, not a visual/browser-quality grade.

## Known limits

- A model can still fail a checker after consuming its normal turn/retry budget; the harness does not yet run the proposed evaluator-guided repair episode.
- The latest matrix shows uneven results: Structured Validation Off and Mini Project Off exposed different failure modes; action correctness alone did not guarantee task quality or completion efficiency.
- The API provider is an experimental provider switch, not evidence that remote-model behavior has been benchmarked comprehensively.
- Path validation, action restrictions, approvals, and workspace leases do not provide OS-level isolation. Avoid secrets and sensitive folders.

## Next meaningful implementation

Implement the bounded evaluator-guided repair design in [the 2026-09-24 specification](superpowers/specs/2026-09-24-agent-lab-evaluator-guided-repair-design.md). It should start only after normal finish gates reach a valid failed evaluator report, grant at most six extra model turns for one repair episode, persist that allowance across interruption, stop on unchanged findings/project state, and expose diagnosis/recheck/outcome in events, Inspector, and matrix results. Preserve honest evaluator authority: only all existing gates plus a fresh evaluator pass can produce success.

The detailed test matrix and acceptance criteria are in the specification; rerun the same 12-cell Gemma E2B matrix after implementation. Do not treat one improved run as proof of a general capability gain.

