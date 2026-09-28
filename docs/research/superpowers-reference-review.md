# Superpowers reference review

Date: 2026-09-19

Agent Lab uses the Superpowers repository as design research, not as a runtime dependency or a source tree to copy into the product.

## Reference snapshot

- Checkout: `.research/superpowers-upstream`
- Repository: `https://github.com/obra/superpowers.git`
- Pinned commit: `5bf4e78011075bcfc0dc295f0724994cd123ee71`
- Commit subject: `Release v6.4.1: diagnosing-superpowers, Native plan execution, OpenCode 2.0 and Muse support (#2338)`
- Inventory at that commit: 231 tracked files and 37,191 text lines

The review covered the complete tracked-tree inventory plus focused reading of the workflow-bearing documentation, skills, implementation/configuration files, and tests. The important material was the bootstrap/porting contract, brainstorming and planning flow, TDD, execution, debugging, review, and verification guidance.

## Patterns retained

Agent Lab keeps the parts that make local work inspectable and resumable:

- A named operational phase instead of a vague “working” spinner.
- Short checkpoints with a summary, next action, and relative artifact list.
- Durable state beside the run/session transcript, exposed to the UI and API.
- Evidence-driven automatic movement: inspection, writes, successful validation, diff review, and honest finish status.
- A repair loop from verification or review back to implementation.
- Explicit verification before reporting completion.

The native contract is intentionally smaller: `intake → inspect → design → plan → implement → verify → review → complete`, with `blocked` as a concrete terminal state until the user restarts the workflow.

## Boundaries and omissions

The implementation does not copy upstream source, skill prose, prompt templates, tests, plugin hooks, or branding. It does not add upstream imports, a plugin loader, subagent dispatch, or Git worktrees. Agent Lab now has an optional native approval gate for mutating tools, but it is an independent, redacted, durable request/decision protocol rather than an upstream port. Hidden reasoning capture remains out of scope. Agent Lab has one local model process and an existing project-folder safety layer; those constraints make a visible checkpoint state and explicit operator gate more useful than pretending it has the full orchestration surface.

The reference checkout remains isolated under `.research/` for future comparison. If upstream code is ever reused, its MIT license and attribution requirements must be carried with that reuse. The current Agent Lab workflow is an independent implementation and has no runtime dependency on the checkout.

## Result

The first native version is deliberately boring in the best way: the harness owns the state, the model can report operational checkpoints, successful tools provide limited automatic evidence, and the console shows exactly that state. The current native slice also persists a review packet with a fingerprinted diff and exposes it in the Changes inspector, so a later edit cannot masquerade as already reviewed. Optional approval steps now pause and resume exact mutating actions without a second model decision. Subagent orchestration and worktree management remain deliberate future work; this is not a claim that Agent Lab is already a full Superpowers port.

