# Local agent lab

This is the first harness around the local Qwen server. It gives the model a task, a managed or user-selected project directory, a small allowlisted tool set, and a turn limit. Every model response and tool result is written to the run directory as JSONL, so we can inspect what actually happened instead of trusting the model's victory speech.

There is also a small desk console for launching and inspecting runs:

```powershell
.\scripts\start-agent-lab-ui.ps1
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). It is bound to loopback only. The console can launch benchmark tasks with their evaluator, or custom tasks with the benchmark gates switched off, and it shows progress plus generated-file previews.

### Real project workspaces

The project-folder field in the console is the agent's actual working directory. Leave it blank to use the managed folder under `agent-lab/runs` or `agent-lab/chat-sessions`; paste an existing absolute path to let the agent inspect and edit that project, or paste a new path and the harness will create it. New chats and benchmark runs both use the selected folder.

The command-line runner accepts the same capability:

```powershell
.\scripts\run-agent-lab.ps1 -TaskFile agent-lab/tasks/001-static-page.md -ProjectDir C:\work\my-project -RunId run-my-project
```

This is direct filesystem access, not a security sandbox. Pick a project deliberately, keep the UI on localhost, and do not point a small local model at credentials or a directory containing secrets.

### Persistent Agent Lab projects

The console now has a project layer for ongoing local-agent work. Create or select a named project in the Projects panel; its workspace lives at `agent-lab/projects/<project-id>/workspace`. Every new chat or run started with that project selected uses that directory, so files survive across conversations and runs. The harness repository itself is not the project unless you explicitly use the existing-folder option.

Scratch work is disposable and lives under the individual chat or run directory. Existing-folder mode is for attaching a project that already lives somewhere else on disk.

### Telegram bridge

The Telegram bridge can run as a per-user Windows Scheduled Task, so it does not depend on a PowerShell window staying open. Install it once from the workspace root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-telegram-bridge.ps1
```

The installer asks for the bot token through hidden input and stores only a Windows DPAPI-encrypted copy in `agent-lab/.secrets/`. The task starts when the signed-in user logs on, restarts after failures, and writes bridge output to `agent-lab/telegram-bridge-logs/bridge.log`.

Use these commands to inspect or rotate it:

```powershell
.\scripts\status-telegram-bridge.ps1
.\scripts\install-telegram-bridge.ps1 -ResetToken
```

The bridge still needs the local Agent Lab UI and local model server to be running. If those are also launched manually, the Telegram task will stay alive and retry while they come back.

### Discord bridge

The Discord bridge uses Node's built-in Gateway WebSocket and does not need a public inbound URL. Start it from the workspace root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-discord-bridge.ps1
```

The runner asks for the Discord bot token through hidden input. The bridge prints a six-digit pairing code; send `!pair <code>` in the Discord server channel that should control Agent Lab. That channel is then restricted to the paired Discord user and mapped to a local Agent Lab session. Use `!status`, `!reset`, `!reasoning off|low|standard|deep|max`, or send a normal prompt. The local UI and model server must be running first.

The current tools are:

- `list_files`
- `read_file`
- `write_file`
- `replace_text` (exact, bounded text replacement with a required match count)
- `apply_patch` (a small supported subset of the familiar patch format; update hunks require an explicit file header, tolerate omitted context prefixes and an omitted final end marker from small models, and validate every file before the batch is written)
- `run_command` (no shell; Python, Node, and `npm test` are allowlisted by config)
- `git_diff` (a diff against the run's initial files)
- `workflow_checkpoint` (an observable phase, summary, next action, and artifact list)
- `finish`

Run the first benchmark from the workspace root:

```powershell
.\scripts\run-agent-lab.ps1 -RunId run-001
```

The generated project is at `agent-lab/runs/<run-id>/project`. The run also contains `events.jsonl`, `transcript.json`, `progress.json`, `summary.json`, `task.md`, and a copy of the config.

To swap Gemma 4 sizes, stop the running llama.cpp process and start the matching file:

```powershell
.\scripts\start-gemma4-local.ps1 -ModelSize E2B
.\scripts\start-gemma4-local.ps1 -ModelSize E4B
```

The launcher keeps E4B as its default for backwards compatibility and reports the selected size in its output. Keep `model` in `agent-lab/harness/config.json` aligned with the running size; the endpoint, harness, task, evaluator, and run format do not need to change. The same config also carries a small `personality` layer; `slight_demon` currently gives the local model a dry, faintly infernal voice without changing its tools or operating rules.

The harness also exposes a model-aware reasoning selector: `off`, `low`, `standard`, `deep`, and `max`. The Agent Lab console applies the selected level to the next interactive message and to newly launched runs. Levels are translated into per-request thinking budgets and output caps; Gemma uses `enable_thinking` plus `reasoning_budget_tokens`, while Qwen also receives its `/think` or `/no_think` template marker. The selector is an abstraction, not a promise that every model supports the same native reasoning semantics.

### Native workflow checkpoints

Agent Lab has a small workflow layer inspired by the useful operational parts of modern coding-agent harnesses, implemented locally in `agent-lab/harness/workflow.py`. Each run and chat starts at `intake` and can move through `inspect`, `design`, `plan`, `implement`, `verify`, `review`, and `complete`; failed work stays observable and can return to `implement` for repair. A concrete blocker is represented separately as `blocked`.

The current snapshot is written to the harness-owned `workflow.json` beside the run or chat transcript. The model can emit a `workflow_checkpoint` action with a short summary, next action, and relative artifact paths. Successful inspections, writes, validation commands, diffs, and finishes also create automatic evidence checkpoints. These summaries describe observable work only; they are not hidden chain-of-thought. The web console reads that same snapshot for the phase rail, Inspector, and Activity feed, so the UI is reporting the harness state rather than inventing a second status system.

The harness accepts a late explicit `plan` checkpoint after automatic evidence has advanced the visible phase, but keeps the current phase and records a `workflow_late_evidence` event. That is deliberately honest about a small model recovering its process without making the state machine a paper shredder.

The Superpowers checkout under `.research/superpowers-upstream` is reference material only. It is not imported, executed, or required to run Agent Lab. See `docs/research/superpowers-reference-review.md` for the boundary and the design decisions this native v1 keeps or leaves out.

### Native skills and workflow gates

Agent Lab has a small native skill catalog in `agent-lab/harness/skills.py`. The bundled defaults are `inspect-and-plan` and `verify-before-finish`; optional bundled skills include `test-driven-changes`, `systematic-debugging`, and `review-before-finish`. A project can add its own skills at `skills/<name>/SKILL.md`; the file needs YAML-style `name` and `description` front matter followed by the skill instructions. Project-local skills are discovered for that project only, and a duplicate name cannot shadow a bundled skill.

The Run dialog shows the selected skills and lets you enable project-local skills or disable a default for one task. The same selection is persisted with chats and runs, exposed through the Inspector, and can be supplied to the CLI as JSON:

```powershell
.\scripts\run-agent-lab.ps1 -RunId run-skilled -SkillOverridesJson '{"enabled":["browser-checks"],"disabled":[]}'
```

`find_skills` is a discovery-only action. Local catalog search is available to the model and UI without installation. Searching skills.sh is deliberately a separate, explicit UI action and requires confirmation; it returns recommendations only and never installs or activates remote code.

Evaluated runs use the workflow gates by default. A successful finish must have observable evidence for inspect, plan, implement, verify, and review. Inspection comes from successful reads/listing, implementation from writes or patches, verification from a successful validation command after a mutation, and review from a fresh `git_diff` after the latest mutation. If the external evaluator rejects a finish, the repair message names failed checks instead of dumping the whole report. Interactive chats and explicitly ungated custom runs remain flexible; use `--no-gates` only when the task is intentionally outside benchmark evaluation.

### Restart-safe conversations

The UI server rehydrates persisted conversations at startup from each session's `session.json`, `transcript.json`, `workflow.json`, `config.json`, and workspace metadata. The conversation list therefore survives closing or restarting the PowerShell process. A session that was marked busy when the process disappeared is reopened with `busy: false`; a completed session is ready to continue, while an in-flight turn is explicitly marked interrupted for recovery. No dead worker is assumed to still exist. The transcript is restored as model context, while the shorter conversation record drives the visible chat. Malformed session records are skipped so one damaged folder cannot prevent the console from starting.

Interactive turns also have a durable job record. A turn that was running when the server stopped is reopened as `interrupted`, not falsely reported as complete and not silently retried. The chat shows a `Resume interrupted turn` action; clicking it creates a new attempt from the latest saved transcript and does not duplicate the visible user message. Model responses, tool results, and worker checkpoints are saved as the turn progresses. If a model call fails, the job is marked `failed` and waits for the same explicit retry. Only the current job attempt may finalize the session, so a stale worker cannot overwrite a newer retry.

The control loop also has bounded recovery. The same malformed response, rejected finish, or tool failure gets one targeted repair opportunity; a second identical failure ends a benchmark as `blocked` with the concrete reason instead of burning the rest of the turn budget. Consecutive duplicate tool calls are stopped before the second dispatch. Patch-context failures give the model a specific recovery instruction to reread the current file and switch to exact replacement instead of replaying a stale hunk; missing required fields such as `args.path` get field-specific guidance. Interactive chats receive the same protection but remain usable after showing the recovery message. The policy is persisted in run summaries and chat session metadata under `recovery`, and its decisions are recorded as `recovery_retry`, `recovery_duplicate_action`, and `recovery_exhausted` events. These controls preserve the workflow gates; they do not manufacture missing evidence.

Context windows are bounded independently from transcript durability. The full `transcript.json` remains available for rehydration, while each model request uses the configured `context_max_tokens` budget and keeps the system prompt plus the newest turns. Older observable turns are reduced to an inspectable operational summary; raw hidden reasoning is neither persisted nor reconstructed. A `context_compacted` event and the current context metadata appear in the run summary, session Inspector, and activity feed, so a long task does not silently become a different conversation.

Harness-owned JSON snapshots and project-file edits use same-directory atomic replacement. A stopped process can leave a hidden temporary file, but it cannot turn the active transcript, session record, workflow snapshot, or edited text file into half a JSON document or a truncated file.

For a new benchmark, change the task file and its completion gates (`required_files`, `require_validation`, and `evaluator`) together; otherwise you would be grading a new task with the old page's ruler.

The static-page checker is deliberately outside the agent project so the model cannot edit its own grading code. The configured evaluator is also a completion gate: the harness rejects a claimed success until the checker passes.

Non-interactive runs also checkpoint `transcript.json` and `progress.json` after each turn and tool observation. If the UI process is restarted before `summary.json` is written, the run is shown as interrupted with its last durable turn, call counts, workflow, and context metadata instead of being mislabeled as an empty aborted run.

```powershell
$py = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py agent-lab/checks/check_static_page.py agent-lab/runs/run-001/project
```

The harness has its own small unit-test set:

```powershell
& $py -m unittest discover -s agent-lab/harness -p 'test_*.py'
```

This version is confined by careful path checks and command restrictions, not by a real operating-system sandbox. It is suitable for controlled experiments in fresh run folders. It is not a license to point an 8B model at your documents, credentials, or main projects.
