# Local agent lab

Agent Lab is a local-first workbench for interactive chats and evaluated project runs with small language models. The Python harness gives the model a managed or user-selected project directory, a bounded action catalog, workflow gates, and a turn limit. Local GGUF inference through llama.cpp is the default; an optional OpenAI-compatible provider uses the same harness controls. Model responses, tool results, and workflow events are recorded so runs can be inspected rather than judged by the model's victory speech.

There is also a small desk console for launching and inspecting runs:

```powershell
.\scripts\start-agent-lab-ui.ps1
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). It is bound to loopback only, and it also refuses requests whose `Host` or `Origin` header is not `127.0.0.1`, `localhost` or `[::1]` on that port, plus any POST that is not `application/json`. That blocks web pages from driving the console (cross-site requests, DNS rebinding) and means a Cloudflare-style tunnel will get `403`; that is deliberate, because anyone who can reach this API can start a model that writes and runs code on this machine. Remote access needs an authenticated layer in front, not a hole in this check. The console can launch benchmark tasks with their evaluator, or custom tasks with the benchmark gates switched off.

The console is an observation view rather than a log viewer. A run page leads with the evaluator's verdict and first-pass versus repaired outcome; a live headline and activity feed narrate each tool call as it happens ("Reading `styles.css`" becomes "Read `styles.css`"); evaluator checks flip as each evaluation lands; and an animated specimen shows the agent's state (thinking, using a tool, waiting, passed, failed). The model's own finish summary is shown last and labelled unverified. Any recorded run can be replayed at 1×, 4× or 16× from its complete event log. Chats show the same narration live and fold each reply's tool work into a "Worked through N steps" disclosure. The Details drawer holds the inspector, project files, the review diff, raw events (without model reasoning) and process output.

The UI is plain ES modules served by `server.py` with no build step: `narration.js` turns harness events into what the console shows and is shared by live view, replay, chats and the showcase; `source.js` talks either to the local API or to recorded showcase files; `specimen.js` draws the animated cell; `app.js` holds the views. Fonts are local Windows faces, so the console works offline.

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

Agent Lab takes one durable workspace lease per project path. A second live chat or run targeting the same persistent or existing folder is rejected with a readable conflict instead of editing concurrently. The lease records the owner and process, is released when a run reaches a terminal state, and reclaims only locks whose process is no longer alive after a restart. This coordinates Agent Lab workers; it is not a substitute for Git or a security sandbox.

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
- `delete_file` (moves the original into the run record before removing it from the project)
- `replace_text` (exact, bounded text replacement with a required match count)
- `apply_patch` (a small supported subset of the familiar patch format; update hunks require an explicit file header, tolerate omitted context prefixes and an omitted opening or final marker (when the patch starts directly at a valid file header) from small models, allow addition-only hunks to use their declared line anchor, and validate every file before the batch is written)
- `run_command` (no shell; Python, Node, and `npm test` are allowlisted by config)
- `git_diff` (a diff against the run's initial files)
- `workflow_checkpoint` (an observable phase, summary, next action, and artifact list)
- `finish`

When a project asks for `python` or `py` and Windows has no launcher on `PATH`, the harness falls back to the bundled interpreter that is already running Agent Lab. That keeps validation reproducible without changing how `node` or project-local commands resolve.

Run the first benchmark from the workspace root:

```powershell
.\scripts\run-agent-lab.ps1 -RunId run-001
```

The web console's Starting point selector now includes four built-in runs:

- `Static page smoke test` — the full Northstar Field Notes UI benchmark and its external evaluator.
- `File round-trip smoke test` — a fast inspect/write/read/validate/diff tool-chain check.
- `Structured validation smoke test` — a small JSON artifact plus a dependency-free local validator.
- `Mini project smoke test` — a smaller three-file browser build for quick iteration.

The selector shows each preset's purpose before launch. Its completion gates come from `agent-lab/tasks/catalog.json`; all four presets have independent checkers outside the generated project that test behavior, not source text (see [Behavioral checkers](#behavioral-checkers)). They judge whether the result works, not how it looks. Direct CLI `-TaskFile` runs retain the configured default gates unless `-NoGates` is supplied. To compare the presets across Gemma reasoning levels sequentially on one local server, run `python agent-lab/benchmarks/catalog_matrix.py`; it writes an incremental JSON report under `agent-lab/benchmarks/results/` after each run. The runner does not automatically resume an interrupted batch.

The generated project is at `agent-lab/runs/<run-id>/project`. The run also contains `events.jsonl`, `output.log`, `transcript.json`, `progress.json`, `summary.json`, `task.md`, and a copy of the config. Evaluator-rejected runs additionally keep their repair episode in `repair.json`.

To inspect the model's returned text from PowerShell, use the run ID shown in Agent Lab:

```powershell
.\scripts\watch-agent-run.ps1 -RunId 'RUN-ID' -Follow
```

Replace `RUN-ID` with the ID shown in Agent Lab. The watcher prints saved model responses, then follows new ones; stop it with Ctrl+C. Omit `-Follow` to print saved responses and exit. If the endpoint returns a separate `reasoning_content` field, the watcher prints that too. Responses appear after each model call completes because the harness currently uses non-streaming requests. The watcher displays only model-response events and never logs request headers.

To swap Gemma 4 sizes, stop the running llama.cpp process and start the matching file:

```powershell
.\scripts\start-gemma4-local.ps1 -ModelSize E2B
.\scripts\start-gemma4-local.ps1 -ModelSize E4B
```

The launcher keeps E4B as its default for backwards compatibility and reports the selected size in its output. Keep `model` in `agent-lab/harness/config.json` aligned with the running size; the endpoint, harness, task, evaluator, and run format do not need to change. The same config also carries a small `personality` layer; `slight_demon` currently gives the local model a dry, faintly infernal voice without changing its tools or operating rules.

The harness also exposes a model-aware reasoning selector: `off`, `low`, `standard`, `deep`, and `max`. The Agent Lab console applies the selected level to the next interactive message and to newly launched runs. Levels are translated into per-request thinking budgets and output caps; Gemma uses `enable_thinking` plus `reasoning_budget_tokens`, while Qwen also receives its `/think` or `/no_think` template marker. The selector is an abstraction, not a promise that every model supports the same native reasoning semantics.

For the local llama.cpp provider, `constrain_local_actions` enables schema-constrained JSON action envelopes. The schema is one variant per action with that action's exact argument fields, types and enum values, so grammar-constrained decoding cannot emit an unknown field (such as `expected_replacements` on `apply_patch`), drop a required field, or invent a workflow phase. The harness still validates every payload before dispatch, because the remote provider does not receive the schema, and gives malformed output one targeted repair attempt. The bundled llama.cpp b11045 server was smoke-tested with the per-action schema on 2026-10-11. `action_output_tokens` is a minimum response ceiling for structured tool turns (default `2048`), independent of the reasoning budget, so `off` remains zero-reasoning while still leaving room for a file-writing action. Set `constrain_local_actions` to `false` only for a local endpoint that does not support it. Remote OpenAI-compatible requests do not receive the local-only response format or output reserve.

### Optional API provider

The local model is still the default, but the header's Model control can switch the same harness to an OpenAI-compatible chat-completions endpoint. Enter the endpoint, model name, and API key; the next chat or run keeps the same project workspace, tools, workflow, approvals, receipts, and recovery logic while using the remote model. The key is held only in the running UI process (or the child run's environment), is never placed in `config.json`, transcripts, summaries, activity events, or Git, and disappears when the process stops. The UI reports only whether a key is loaded.

For a CLI experiment, set `AGENT_LAB_API_KEY` in the current PowerShell session and override the provider without editing the checked-in config:

```powershell
$py = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:AGENT_LAB_API_KEY = 'paste-key-here'
& $py agent-lab/harness/agent_harness.py -TaskText 'Inspect the project and report back.' -Provider openai_compatible -Endpoint 'https://api.openai.com/v1/chat/completions' -Model 'your-model' -NoGates
```

Do not paste a real key into a task, issue, transcript, or committed file. A remote model is an experiment switch, not a replacement for the local-first safety boundary.

### Native workflow checkpoints

Agent Lab has a small workflow layer inspired by the useful operational parts of modern coding-agent harnesses, implemented locally in `agent-lab/harness/workflow.py`. Each run and chat starts at `intake` and can move through `inspect`, `design`, `plan`, `implement`, `verify`, `review`, and `complete`; failed work stays observable and can return to `implement` for repair. A concrete blocker is represented separately as `blocked`.

The current snapshot is written to the harness-owned `workflow.json` beside the run or chat transcript. The model can emit a `workflow_checkpoint` action with a short summary, next action, and relative artifact paths. Successful inspections, writes, validation commands, diffs, and finishes also create automatic evidence checkpoints. These summaries describe observable work only; they are not hidden chain-of-thought. The web console reads that same snapshot for the phase rail, Inspector, and Activity feed, so the UI is reporting the harness state rather than inventing a second status system.

The harness accepts a late explicit `plan` checkpoint after automatic evidence has advanced the visible phase (implement, verify or review), but keeps the current phase and records a `workflow_late_evidence` event. Repeating it is harmless; it used to raise a backward-transition error that ended finished runs before evaluation. That is deliberately honest about a small model recovering its process without making the state machine a paper shredder.

### Durable change review

Every successful `git_diff` creates a durable `review.json` beside the run or chat record. It contains a deterministic project fingerprint, added/modified/deleted file records, the captured diff, the last validation/evaluator evidence, and the workflow evidence that existed when the review was made. Later edits make the packet visibly stale, so a green review cannot quietly survive a new mutation. The Details drawer exposes the same packet in its Changes tab; it is the harness's review surface, not a second UI-only interpretation of the transcript.

### Optional operator approvals

Tool use defaults to `auto`, but the console's Tools selector can switch a chat or new run to `confirm`. In that mode, reads remain automatic while project mutations (`write_file`, `delete_file`, `replace_text`, `apply_patch`, and `run_command`) create a durable `approval.json` request and pause with `waiting_approval`. The UI shows a redacted action summary; the exact arguments stay in the run record so approval resumes the same action without asking the model to invent it again. Denial becomes an explicit tool observation, allowing the model to adapt. The decision and final action remain in the audit trail. The CLI supports the same flow with `--approval-mode confirm` and `--approval-decision approve|deny`; `auto` remains the unattended default.

The Superpowers checkout under `.research/superpowers-upstream` is reference material only. It is not imported, executed, or required to run Agent Lab. See `docs/research/superpowers-reference-review.md` for the boundary and the design decisions this native v1 keeps or leaves out.

### Native skills and workflow gates

Agent Lab has a small native skill catalog in `agent-lab/harness/skills.py`. The bundled defaults are `inspect-and-plan` and `verify-before-finish`; optional bundled skills include `test-driven-changes`, `systematic-debugging`, and `review-before-finish`. A project can add its own skills at `skills/<name>/SKILL.md`; the file needs YAML-style `name` and `description` front matter followed by the skill instructions. Project-local skills are discovered for that project only, and a duplicate name cannot shadow a bundled skill.

The Run dialog shows the selected skills and lets you enable project-local skills or disable a default for one task. The same selection is persisted with chats and runs, exposed through the Inspector, and can be supplied to the CLI as JSON:

```powershell
.\scripts\run-agent-lab.ps1 -RunId run-skilled -SkillOverridesJson '{"enabled":["browser-checks"],"disabled":[]}'
```

`find_skills` is a discovery-only action. Local catalog search is available to the model and UI without installation. Searching skills.sh is deliberately a separate, explicit UI action and requires confirmation; it returns recommendations only and never installs or activates remote code.

Evaluated runs use the workflow gates by default. A successful finish must have observable evidence for inspect, plan, implement, verify, and review. Inspection comes from successful reads/listing, implementation from writes or patches, verification from a successful validation command after a mutation, and review from a fresh `git_diff` after the latest mutation. If the external evaluator rejects a finish, the repair message names failed checks instead of dumping the whole report. Interactive chats and explicitly ungated custom runs remain flexible; use `--no-gates` only when the task is intentionally outside benchmark evaluation.

### Evaluator-guided run repair

When a run requests success after satisfying its workflow, file, validation and review gates, a valid failed evaluator report starts one repair episode. Checker findings give the model requirement IDs, bounded descriptions and relative artifact hints. They are untrusted data, not instructions or new permissions. The model must make its own edits and earn fresh validation, review and evaluator evidence.

The normal turn budget remains unchanged. An active episode may use up to six additional model calls; `max_repair_turns` may lower that allowance but cannot raise it above six. Unchanged findings against an unchanged project stop as `no_progress`. Protocol/tool failures still use the existing generic recovery limits. Invalid reports, contradictory grades, checker crashes/timeouts and infrastructure findings end as errors, never as repair opportunities.

While an episode is open, every model request carries the last evaluation's findings appended to its latest message (request-only; the transcript is unchanged), because context compaction otherwise drops the single findings message within a few turns. The reminder ends with a status derived from the project fingerprint and fresh evidence (no edits yet, validate next, review next, or call finish now), since the findings list cannot change until finish runs the evaluator again; a static reminder made models repeat fixes that had already succeeded. The allowance is reserved durably before each extra request. `repair.json` survives interruptions and explicit resumes; a resumed run gets the existing fresh normal budget, but never replenishes its six-call repair extension. Damaged or missing episode snapshots produce explicit resume errors. The activity feed and Details Inspector expose the episode outcome, initial/remaining findings and turn usage. Chats are unchanged.

Matrix reports retain final `passed` and separately record `first_pass_passed` (null if no valid evaluation occurred), `repair_attempted`, `repair_outcome`, `repair_episode_turns`, `extension_turns_used`, and initial/final finding IDs. A repaired pass is not a first-pass pass.

### Restart-safe conversations

The UI server rehydrates persisted conversations at startup from each session's `session.json`, `transcript.json`, `workflow.json`, `config.json`, and workspace metadata. The conversation list therefore survives closing or restarting the PowerShell process. A session that was marked busy when the process disappeared is reopened with `busy: false`; a completed session is ready to continue, while an in-flight turn is explicitly marked interrupted for recovery. No dead worker is assumed to still exist. The transcript is restored as model context, while the shorter conversation record drives the visible chat. Malformed session records are skipped so one damaged folder cannot prevent the console from starting.

Interactive turns also have a durable job record. A turn that was running when the server stopped is reopened as `interrupted`, not falsely reported as complete and not silently retried. The chat can stop a live turn cooperatively, or show a `Resume interrupted turn` action; retrying creates a new attempt from the latest saved transcript and does not duplicate the visible user message. Model responses, tool results, and worker checkpoints are saved as the turn progresses. If a model call fails, the job is marked `failed` and waits for the same explicit retry. Only the current job attempt may finalize the session, so a stale worker cannot overwrite a newer retry.

Tool calls also have a durable `tool-receipt.json` lifecycle. The harness records the exact action before dispatch, records the result immediately after dispatch, and settles the receipt only after the tool observation is safely in the transcript and progress snapshot. If a worker stops with a completed receipt, the result is replayed as an observation without dispatching the side effect again. If it stops while the receipt is still pending, the outcome is marked unknown and the next attempt is told to inspect the project before repeating anything. The public UI receives only a redacted receipt summary; exact arguments and results stay in the harness record.

The control loop also has bounded recovery. The same malformed response, rejected finish, or tool failure gets one targeted repair opportunity; a second identical failure ends a benchmark as `blocked` with the concrete reason instead of burning the rest of the turn budget. Consecutive duplicate tool calls are stopped before the second dispatch, and the refusal names the next workflow step from recorded evidence (validate, review with `git_diff`, finish, or edit the files in open evaluator findings). Patch-context failures give the model a specific recovery instruction to reread the current file and switch to exact replacement instead of replaying a stale hunk; missing required fields such as `args.path` get field-specific guidance. Interactive chats receive the same protection but remain usable after showing the recovery message. The policy is persisted in run summaries and chat session metadata under `recovery`, and its decisions are recorded as `recovery_retry`, `recovery_duplicate_action`, and `recovery_exhausted` events. These controls preserve the workflow gates; they do not manufacture missing evidence.

Context windows are bounded independently from transcript durability. The full `transcript.json` remains available for rehydration, while each model request uses the configured `context_max_tokens` budget and keeps the system prompt plus the newest turns. Older observable turns are reduced to an inspectable operational summary; raw reasoning is never replayed into model context. If a run's provider returns a separate `reasoning_content` field, the run event log preserves it for manual inspection, but the harness does not infer or reconstruct reasoning when that field is absent. A `context_compacted` event and the current context metadata appear in the run summary, session Inspector, and activity feed, so a long task does not silently become a different conversation. For the local provider, `model_context_tokens` (default config `8192`, matching the launcher's `-c`) shrinks that budget so the prompt plus the request's `max_tokens` fit in llama.cpp's shared window, with a 1.2x margin for the character-based token estimate. Without it, Deep/Max turns could fill the window and be cut off mid-JSON; a cut-off reply now gets a specific instruction to send smaller content. If you raise the launcher's context size, raise `model_context_tokens` to match.

Harness-owned JSON snapshots and project-file edits use same-directory atomic replacement. A stopped process can leave a hidden temporary file, but it cannot turn the active transcript, session record, workflow snapshot, or edited text file into half a JSON document or a truncated file.

For a new benchmark, change the task file and its completion gates (`required_files`, `require_validation`, and `evaluator`) together; otherwise you would be grading a new task with the old page's ruler.

The static-page checker is deliberately outside the agent project so the model cannot edit its own grading code. The configured evaluator is also a completion gate: the harness rejects a claimed success until the checker passes.

### Behavioral checkers

The checkers use what the model built. For the static page and mini project, `checks/browser_checks.py` serves the project from a private `127.0.0.1` server (no directory listings, nothing outside the project, symlinks included) and runs `checks/browser_probe.mjs`, which starts the installed Edge or Chrome headless with a throwaway profile and drives it over the DevTools protocol using Node's built-in WebSocket; there are no npm packages and no browser download. Every request to another origin is blocked and recorded, and host names do not resolve. The probe types two observations and submits them, presses Tab through the page, clicks and keyboard-activates the mini project's first button, measures text contrast (3:1 floor), and shrinks the viewport to a 375px phone. The file round-trip module is imported and its `status` export read; the structured validator is run against the valid report and four invalid ones.

Each failed check carries an `evidence` string with what was observed, for example `clicking button.submit-btn "Submit Observation" reloaded the page instead of adding a card`. The repair reminder passes it to the model. A missing browser or Node, or a probe malfunction, is an infrastructure finding, so the run errors instead of asking the model to repair its environment.

The browser checks need Node and Edge, Chrome or Chromium in its usual install location. Set `AGENT_LAB_BROWSER` to the executable's full path to use another one. A page check takes several seconds, so the evaluator runs under its own `evaluator_timeout_seconds` (default 90, never shorter than `command_timeout_seconds`). The checker tests skip their browser fixtures, rather than fail, on a machine without a browser.

### Ablations

`disabled_actions` in the harness config (CLI: `--disable-action NAME`, repeatable; matrix runner: `--disable-action NAME --variant LABEL`) withholds an action from the model for an experiment. Today only `apply_patch` can be withheld, because only its prompt text is fully removable; the finish gates need the other actions. The action disappears from the system prompt, from the grammar schema local models are constrained by, and from action validation, and the setting is saved in the run's `config.json` so a resume keeps it. The matrix results file records the variant label. Results: [2026-10-16 ablation](benchmarks/2026-10-16-no-apply-patch-ablation.md).

When a checker changes, grade recorded runs again to see what the old numbers meant. The script reads runs and never modifies them; it executes their model-written code exactly as the checker does during a run:

```powershell
$py = Join-Path $env:USERPROFILE '.codex\tools\python\bin\python3.14.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
& $py agent-lab/benchmarks/regrade_runs.py matrix-20261011-201925 --workers 3
```

It prints recorded versus current verdicts per task, the most common failures and the runs that flipped, and saves the rows under `agent-lab/benchmarks/results/`.

Non-interactive runs also checkpoint `transcript.json` and `progress.json` after each turn and tool observation, while the UI server appends worker stdout to `output.log`. If the UI process is restarted before `summary.json` is written, the run is shown as interrupted with its last durable turn, call counts, workflow, context metadata, and recovered raw output instead of being mislabeled as an empty aborted run.

Interrupted benchmark runs are resumable. Each run keeps an immutable `initial-project/` snapshot plus `initial-snapshot.json`, restores its transcript, workflow evidence, recovery state, and last checkpoint, and can continue from the last completed turn with:

```powershell
.\scripts\run-agent-lab.ps1 -ResumeRun run-001
```

The console exposes `Stop run` while a benchmark is active and `Resume run` when an interrupted record is selected. Stopping terminates the harness worker without deleting the project or audit trail. Resuming gives the worker a fresh configured turn budget while preserving the existing project and audit trail; terminal records are intentionally not restartable.

```powershell
$py = Join-Path $env:USERPROFILE '.codex\tools\python\bin\python3.14.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
& $py agent-lab/checks/check_static_page.py agent-lab/runs/run-001/project
```

Run all Python unit-test groups and the browser UI contract checks together:

```powershell
$py = Join-Path $env:USERPROFILE '.codex\tools\python\bin\python3.14.exe'
if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }

foreach ($area in @('harness', 'checks', 'ui', 'benchmarks')) {
    & $py -m unittest discover -s "agent-lab/$area" -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed in agent-lab/$area" }
}

$node = Join-Path $env:USERPROFILE '.codex\tools\node\node-v24.21.0-win-x64\node.exe'
if (-not (Test-Path -LiteralPath $node)) { $node = 'node' }
& $node --test agent-lab/ui/test_ui_contract.mjs agent-lab/ui/test_narration.mjs
if ($LASTEXITCODE -ne 0) { throw 'UI contract or narration tests failed' }
foreach ($module in @('app.js', 'narration.js', 'source.js', 'specimen.js')) {
    & $node --check "agent-lab/ui/$module"
    if ($LASTEXITCODE -ne 0) { throw "UI syntax check failed: $module" }
}
```

This exercises the harness, checker, UI-server, benchmark, console contract and narration suites. It does not start a model server or run the slower Gemma matrix.

### Public showcase

The GitHub Pages site is the same console in read-only showcase mode. To refresh its recordings, pick runs worth showing and export them:

```powershell
& $py scripts/export_showcase.py --run matrix-20261011-201925-004-off --chat chat-20261011-221823
```

With no arguments the script exports its curated default set. It reads run and chat records from disk without modifying them, replaces local paths, drops model reasoning and raw model output, clips long values, includes only small text project files, and refuses to write anything if a local path survives. Review `site/showcase/` before committing; only push recordings you are happy to make public. Opening the console on any non-loopback host, or with `?showcase`, uses the recordings instead of the API.

Path checks and command restrictions reduce risk but do not provide operating-system isolation. Use disposable projects for early tests; attach an existing project only deliberately, keep credentials outside model-visible folders, and use Git or another backup for work you care about.
