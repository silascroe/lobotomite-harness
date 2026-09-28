# SDD ledger — plan: docs/superpowers/plans/2026-09-19-agent-lab-workflow.md

Pre-flight: the workspace is not a Git checkout, so no worktree or commit range is available. The reference checkout is isolated at `.research/superpowers-upstream` and pinned to `5bf4e78011075bcfc0dc295f0724994cd123ee71`.

Ruling: use native inline execution — the user explicitly asked to plan and implement in this session, and Agent Lab has no subagent runner. The cost is a final self-review instead of independent per-task reviewers.

Task 1: complete — `unittest discover -s agent-lab/harness -p 'test_workflow.py' -v` → 7/7 passed.
Task 2: complete — `unittest discover -s agent-lab/harness -p 'test_*.py' -v` → 16/16 passed after adding workflow protocol, persistence, and evidence mapping.
Task 3: complete — focused server workflow tests → 2/2 passed; harness discovery → 16/16 passed.
Task 4: complete — UI contract → 13 assertions passed; JavaScript syntax passed; live health/reasoning/projects endpoints → 200/200/200.
Ruling: keep phase-aware automatic evidence after explicit checkpoints, with only the documented verify/review repair loop moving back to implement — the design's evidence table and repair-loop contract require observable progress without forcing every model to emit a checkpoint; cost if wrong: a model that checkpoints too aggressively could see an automatic phase change sooner than expected, but only from successful, transition-valid evidence.
Final review: self-review (no subagent tool). Goals and non-goals checked against the spec; 15 changed-or-created paths present; no Agent Lab runtime import of the reference checkout; final verification suite green. No deferred minors recorded.

