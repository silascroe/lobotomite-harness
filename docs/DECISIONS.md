# Durable design decisions

This is a short index, not a second archive of design documents. The linked specs retain detailed rationale, alternatives, and acceptance criteria.

| Decision | Current rule | Source |
| --- | --- | --- |
| Local-first, provider-independent harness | Local llama.cpp is the default; an OpenAI-compatible provider is optional, but uses the same project, action, workflow, approval, and persistence controls. | [Operator guide](../agent-lab/README.md#optional-api-provider) |
| Harness owns completion authority | Model output alone cannot declare a benchmark pass. Workflow/file/validation/review gates and the independent evaluator remain authoritative. | [Control-loop spec](superpowers/specs/2026-09-21-agent-lab-control-loop.md) |
| Bounded named actions, not an unrestricted shell | Tool arguments are validated by action; command execution is limited by configuration. This is risk reduction, not an OS sandbox. | [Control-loop spec](superpowers/specs/2026-09-21-agent-lab-control-loop.md) |
| The model makes project edits; evaluator feedback guides them | The harness does not auto-fix failed requirements or skip checks. Evaluator-guided repair, when implemented, remains bounded and must earn a fresh passing evaluation. | [Repair design](superpowers/specs/2026-09-24-agent-lab-evaluator-guided-repair-design.md) |
| One active worker per shared project path | Workspace leases reject competing Agent Lab workers for the same persistent/existing project directory; the lease is concurrency coordination, not a security boundary. | [Operator guide](../agent-lab/README.md#persistent-agent-lab-projects) |

When a decision changes, update its canonical spec or implementation documentation first, then revise this index rather than letting the two drift apart.

