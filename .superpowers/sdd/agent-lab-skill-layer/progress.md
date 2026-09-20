# SDD ledger — plan: inline Agent Lab skill layer and workflow gates

Ruling: Implement in the current workspace after the requested Git baseline — a new empty repository has no existing branch or worktree to isolate against, and creating one would add ceremony without isolating any prior history. Cost if wrong: the work is on the local default branch and can be moved later.

Pre-flight: Task 1 produces the skill registry and selection contract consumed by the harness and UI; Task 2 consumes that contract for prompt injection and finish gates; Task 3 consumes both for API/UI persistence and discovery. Interfaces will be verified with tests before each consumer is implemented.

Tasks:

- Task 1: skill registry, built-in skills, project-local discovery, and deterministic selection — complete (tests: `python -m unittest discover -s agent-lab/harness -p 'test_*.py'` -> 28/28)
- Task 2: harness prompt injection and inspect/plan/implement/verify finish gates — complete (tests: `python -m unittest discover -s agent-lab/harness -p 'test_*.py'` -> 32/32)
- Task 3: server/UI skill controls, discovery endpoint, persisted snapshots, and CLI override handoff — complete (tests: server 15/15; UI contract 14/14; harness 32/32)
- Task 4: documentation, end-to-end smoke verification, and final review — pending
