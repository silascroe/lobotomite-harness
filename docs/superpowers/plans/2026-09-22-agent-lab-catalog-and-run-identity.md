# Agent Lab Run Catalog and Run Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a useful built-in run catalog with task-specific completion gates, then preserve the selected preset in run records so future benchmark comparisons have an honest identity.

**Architecture:** Markdown files remain the source of task instructions. A small adjacent JSON catalog supplies descriptions and per-task gate profiles; the UI receives both through the existing `/api/tasks` endpoint. When a preset is launched, the server passes its validated profile to the harness, which applies only that run's gates and persists the preset metadata in `config.json`, `progress.json`, and `summary.json`.

**Tech Stack:** Python 3, Node.js test runner, plain HTML/CSS/JavaScript, JSON task metadata.

**Spec:** User-approved run catalog and evaluation follow-on in the current conversation.

## Global Constraints

- Built-in presets must remain local, offline, and usable in a fresh isolated project.
- Preset runs must not inherit the static-page evaluator or required files unless that preset explicitly declares them.
- Custom tasks keep the existing behavior: the UI launches them ungated unless the user explicitly changes that flow.
- Never persist API keys or include them in task metadata, run identity, or browser-visible summaries.
- Existing static-page behavior and historical run records must remain readable.

## Review Focus

- A catalog entry with no evaluator must still pass its own required-file and validation gates without inheriting the old evaluator.
- A malformed or unknown preset name must be rejected before a worker is launched.
- A run started from a preset must preserve its name and title after the process finishes or is rehydrated.
- A custom task must not accidentally receive a preset gate profile.
- Existing CLI runs using `--task-file` must retain the current global-config behavior.

---

### Task 1: Add the curated built-in run catalog

**Files:**
- Create: `agent-lab/tasks/catalog.json`
- Create: `agent-lab/tasks/002-file-roundtrip.md`
- Create: `agent-lab/tasks/003-structured-validation.md`
- Create: `agent-lab/tasks/004-mini-project.md`
- Modify: `agent-lab/ui/server.py:327-340`
- Modify: `agent-lab/ui/test_ui_contract.mjs`
- Modify: `agent-lab/README.md` near the benchmark instructions

**Interfaces:**
- Consumes: existing Markdown task files and `task_catalog()`.
- Produces: `/api/tasks` entries shaped as `{name, title, content, description, profile}` where `profile.gates` contains `required_files`, `require_validation`, `require_workflow_gates`, and optional `evaluator`.

- [ ] **Step 1: Write the failing catalog contract test**

Add this test to `agent-lab/ui/test_ui_contract.mjs` after the existing file reads:

```js
test("built-in run catalog contains focused gate-compatible presets", () => {
  const tasksDir = fileURLToPath(new URL("../tasks/", import.meta.url));
  const expected = [
    ["001-static-page.md", "Static page smoke test"],
    ["002-file-roundtrip.md", "File round-trip smoke test"],
    ["003-structured-validation.md", "Structured validation smoke test"],
    ["004-mini-project.md", "Mini project smoke test"],
  ];
  for (const [name, title] of expected) {
    const content = readFileSync(`${tasksDir}${name}`, "utf8");
    assert.match(content, new RegExp(`^# ${title}$`, "m"), `${name} title`);
    assert.match(content, /workflow_checkpoint/);
    assert.match(content, /git_diff/);
    assert.match(content, /finish/);
  }
  const catalog = JSON.parse(readFileSync(`${tasksDir}catalog.json`, "utf8"));
  assert.deepEqual(Object.keys(catalog.tasks).sort(), expected.map(([name]) => name).sort());
  for (const entry of Object.values(catalog.tasks)) {
    assert.equal(typeof entry.description, "string");
    assert.ok(entry.gates);
    assert.equal(entry.gates.require_workflow_gates, true);
  }
});
```

- [ ] **Step 2: Run the focused test and verify it fails for the missing catalog files**

Run: `node --test agent-lab/ui/test_ui_contract.mjs`

Expected: FAIL in the new catalog test because `002-file-roundtrip.md` does not exist yet.

- [ ] **Step 3: Add the task files and metadata**

Create four profiles in `catalog.json`:

```json
{
  "version": 1,
  "tasks": {
    "001-static-page.md": {
      "description": "Full UI build benchmark with an external static-page evaluator.",
      "gates": {
        "required_files": ["index.html", "styles.css", "app.js"],
        "require_validation": true,
        "require_workflow_gates": true,
        "evaluator": "agent-lab/checks/check_static_page.py"
      }
    },
    "002-file-roundtrip.md": {
      "description": "Fast tool-chain smoke test: inspect, write, read, validate, and review.",
      "gates": {
        "required_files": ["agent-check.md", "agent-check.mjs"],
        "require_validation": true,
        "require_workflow_gates": true
      }
    },
    "003-structured-validation.md": {
      "description": "Create a small machine-readable report and validate its shape locally.",
      "gates": {
        "required_files": ["health-report.json", "validate-report.mjs"],
        "require_validation": true,
        "require_workflow_gates": true
      }
    },
    "004-mini-project.md": {
      "description": "A smaller multi-file browser build for quick UI iteration.",
      "gates": {
        "required_files": ["index.html", "styles.css", "app.js"],
        "require_validation": true,
        "require_workflow_gates": true
      }
    }
  }
}
```

The three new Markdown tasks must explicitly require an initial inspection, short plan checkpoint, implementation, local validation with an allowlisted command, `git_diff`, and an honest `finish` action. They must not require network access, frameworks, packages, or external assets.

- [ ] **Step 4: Load catalog metadata without breaking legacy task files**

Update `task_catalog()` to read `agent-lab/tasks/catalog.json` through the existing safe JSON helper. For each Markdown file, preserve the current title/content behavior and add the matching `description` and `profile`; when metadata is absent, return an empty description and an empty profile rather than failing the entire catalog.

- [ ] **Step 5: Document the choices**

Add a short README section listing the four presets and what each is intended to measure. State that the selector’s completion gates come from `catalog.json`, while direct CLI `--task-file` runs retain the configured default gates unless `--no-gates` is supplied.

- [ ] **Step 6: Run the focused UI contract test and the existing test suites**

Run: `node --test agent-lab/ui/test_ui_contract.mjs`

Expected: all UI contract tests pass, including the four-preset catalog test.

Run: `& 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s agent-lab/harness -p 'test_*.py'`

Expected: the existing harness suite remains green.

- [ ] **Step 7: Commit the catalog**

```powershell
git add agent-lab/tasks agent-lab/ui/server.py agent-lab/ui/test_ui_contract.mjs agent-lab/README.md
git -c user.name=Codex -c user.email=codex@local commit -m "Add curated Agent Lab run catalog"
```

### Task 2: Apply task profiles and persist run identity

**Files:**
- Modify: `agent-lab/harness/agent_harness.py` in argument parsing and configuration setup
- Modify: `agent-lab/harness/test_agent_harness.py`
- Modify: `agent-lab/ui/server.py` in `start_run()`, `run_state()`, and `run_summaries()`
- Modify: `agent-lab/ui/app.js` in `startRun()`, `renderRunList()`, and inspector rendering
- Modify: `agent-lab/ui/index.html` in the run record header/details surface
- Modify: `agent-lab/ui/test_ui_contract.mjs`

**Interfaces:**
- Consumes: `/api/tasks` profile data from Task 1.
- Produces: `--task-profile-json` for the harness; persisted `task_profile` metadata in run records; browser-visible `task_profile` summaries and task labels.

- [ ] **Step 1: Write failing tests for profile isolation and run identity**

Add a harness test that applies a profile to a base config containing the static-page evaluator and asserts the profile replaces `required_files`, `require_validation`, `require_workflow_gates`, and removes the evaluator when it is absent. Add a server test that rejects an unknown `task_name`, and a UI contract assertion that the launch payload includes `task_name` and the inspector renders `task_profile`.

- [ ] **Step 2: Run those tests and verify they fail**

Run: `& 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest agent-lab/harness/test_agent_harness.py agent-lab/ui/test_server_workflow.py`

Expected: FAIL because the profile application helper, preset validation, and launch metadata do not exist yet.

- [ ] **Step 3: Add minimal harness profile application**

Add `apply_task_profile(config, profile)` in `agent_harness.py`. It must copy the base config, validate the profile and gate types, store a public `task_profile` object, replace the four gate keys from `profile["gates"]`, and remove `evaluator` when the profile does not declare one. Add `--task-profile-json` to the CLI and apply it before `--no-gates`, so an explicit no-gates launch still wins.

- [ ] **Step 4: Pass validated profiles from the server**

Accept optional `task_name` in `start_run()`. If present, find the exact catalog entry, reject unknown names with `ApiError(..., 400)`, and pass its profile as `--task-profile-json`. If absent, do not pass a profile. The existing task text remains the actual prompt sent to the model.

- [ ] **Step 5: Persist and expose identity**

Persist `task_profile` through the harness’s config/progress/summary snapshots. Expose it in `run_state()` and `run_summaries()`. Send `task_name` from the UI for non-custom presets. Render the preset title in recent runs and add a `Task` row in the details inspector; fall back cleanly for historical runs with no profile.

- [ ] **Step 6: Run focused tests, then the full suites**

Run the failing tests from Step 2 and confirm they pass.

Run: `node --test agent-lab/ui/test_ui_contract.mjs`

Expected: all UI contract tests pass.

Run: `& 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s agent-lab/harness -p 'test_*.py'`

Expected: all harness tests pass.

Run: `& 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest agent-lab/ui/test_server_workflow.py`

Expected: all server workflow tests pass, including unknown-preset rejection.

- [ ] **Step 7: Commit the profile-aware run identity slice**

```powershell
git add agent-lab/harness/agent_harness.py agent-lab/harness/test_agent_harness.py agent-lab/ui/server.py agent-lab/ui/app.js agent-lab/ui/index.html agent-lab/ui/test_ui_contract.mjs
git -c user.name=Codex -c user.email=codex@local commit -m "Make Agent Lab runs task-aware"
```

### Next step after this plan

Run the four presets at Gemma reasoning levels Off, Standard, and Deep, record pass/fail, elapsed time, model/tool calls, validation, and changed files, then use those real results to choose the next harness change. The likely next feature is a compact comparison view over these persisted fields; it should not be built until the matrix reveals which differences are actually useful.

