# Agent Lab architecture

Agent Lab wraps a model with a project workspace, constrained actions, an observable workflow, and independent completion checks. The browser UI is a local operator console; it is not the security boundary.

## Runtime flow

Operator ⇄ browser UI at 127.0.0.1:8787 ⇄ Python UI server ⇄ Agent harness ⇄ model provider.

The default provider is the llama.cpp server at 127.0.0.1:8080. An optional OpenAI-compatible API uses the same harness controls. The harness applies bounded tool actions to the selected project workspace, asks configured evaluators to grade benchmark work, and writes run/session evidence that the UI reads back.

## Components

| Area | Responsibility |
| --- | --- |
| agent-lab/ui/ | Serves the browser console, exposes local APIs, manages interactive sessions and run workers, and renders activity from persisted harness events. |
| agent-lab/harness/agent_harness.py | Owns the agent loop, provider calls, action validation and dispatch, finish gates, and run/session logging. Supporting modules separate workflow, recovery, context limits, approvals, persistence, review packets, job state, skills, and workspace locks. |
| agent-lab/harness/provider.py | Selects the configured local provider or optional OpenAI-compatible chat-completions provider. Both use the same harness controls. |
| agent-lab/tasks/ and agent-lab/checks/ | Define the task catalog and independent checkers. Evaluators grade artifacts; they do not edit the project. |
| agent-lab/benchmarks/ | Runs catalog matrices and records outcomes separately from ordinary app state. |
| scripts/ | Starts the local model and UI, runs CLI tasks, manages bridges, and inspects recorded model responses. |
| models/ and runtime/ | Local GGUF files and llama.cpp binaries. They are machine-local assets and are ignored by Git. |

## Run lifecycle and evidence

The harness sends the task and bounded conversation context to the chosen provider. The model returns a structured action; the harness validates its name, argument shape, and applicable path/command limits before applying it to the selected workspace. Tool results and workflow checkpoints feed back into the next model turn. For evaluator-gated runs, finish is accepted only after the configured workflow, required-file, validation, review, and evaluator gates pass. Interactive chats and explicitly ungated custom work follow their configured finish policy and are not equivalent to an evaluated benchmark pass.

Run/session records keep the transcript and event ledger alongside workflow, progress, summary, and review snapshots. The UI polls those records and presents a readable activity feed plus the underlying inspection surfaces. This is an auditable harness trace, not hidden chain-of-thought.

Benchmark tasks invoke checkers such as agent-lab/checks/check_static_page.py against the generated project. The UI can also launch ungated custom work; that mode is not equivalent to a benchmark pass.

## Workspace and trust boundaries

Scratch work, persistent Agent Lab projects, and explicitly attached existing folders have different lifetimes, but all are real directories on the host. A workspace lease prevents concurrent Agent Lab workers from targeting the same persistent/existing path. It is coordination, not isolation from the operating system or other processes. Tool-level path checks and command allowlists likewise reduce mistakes but do not turn the harness into a VM or container sandbox.

The UI binds to loopback at port 8787; the default local inference endpoint is loopback port 8080. An optional remote API key is held at runtime and is not supposed to enter checked-in config or run records. Keep secrets outside model-visible workspaces.

For current implementation gaps see [STATUS.md](STATUS.md). Detailed rationale and acceptance criteria live with the dated [specifications](superpowers/specs/) and [plans](superpowers/plans/).

