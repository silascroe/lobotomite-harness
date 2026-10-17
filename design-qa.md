# Agent Lab console QA

Date: 2026-10-17
Result: blank-slate console redesign ("flight recorder") verified against the live API, live run and chat paths, replay, the read-only showcase build, desktop and phone width.

## Direction

The console is an instrument for one question: what does each part of the harness do to a small model's run, judged by whether the result works. It reads as a flight recorder: dark panels, a monospace readout for every number, cyan for the model's own signal, and amber and red only for abnormal states (the ISA-101 habit of keeping colour for what needs attention). Type is IBM Plex Mono and IBM Plex Sans Condensed, bundled under the SIL Open Font License so the console works offline and the public page makes no third-party requests.

The four views came from four separate directions explored as mockups: the time-aligned recorder strip, a control-room process line with an alarm list, an experiments-first bench, and a file lens showing what the model believed versus what was on disk. All four are kept as routes in one console: Bench is the home page; a run has Recorder, Process, Files, Checks and Log views.

On a phone the layout changes rather than shrinks: a bottom tab bar replaces the top navigation; the recorder strip becomes a vertical tape with one row per turn and an overview strip above it, and a tapped row opens that turn inline; the process line runs top to bottom; the file grid transposes to turns × files; dialogs become full-screen sheets; the chat composer replaces the tab bar.

## Verification

- `node --test agent-lab/ui/test_ui_contract.mjs agent-lab/ui/test_model.mjs`: 15 tests pass. The contract suite covers the shell, every run view, the start-run payload, chat and approval calls, the endpoints, the showcase refusing every mutating action, escaping of model and file text, bundled fonts, the phone layout and reasoning staying out of the log. The model suite reads the committed showcase recordings and checks the recorder, alarms, process state, the context-miss replay and the bench statistics against the 2026-10-16 reports (21/36, 42–73%, 22/36, p = 1.00, failure causes).
- `python -m unittest discover -s agent-lab/ui -p 'test_*.py'`: 48 server tests pass, including the new benchmark catalog test.
- The context-miss detector replays the harness's `apply_update` hunk by hunk. Both runs it flags (`065825-001-deep` turn 21, `065825-003-deep` turn 10) were confirmed by running the harness's own `apply_update`, instrumented, on the recorded inputs: both took the line-number fallback.
- Browser checks (headless Chromium, 1440×1000 and 390×844): no horizontal overflow at either width; turn selection, arrow keys, replay at 16× with the turn following the cursor, scrubbing, bench experiment tabs and cell links, the new-run dialog, the provider dialog, and Checks and Log views all work with no page errors.
- Live paths, without a model server: a run started from the dialog navigated to its page and settled on ERROR with the endpoint failure as the reason; a new chat sent a message and showed the failed-turn banner with Retry. Testing this exposed a start-up race (the server's output capture could create the run folder before the harness did), fixed in `prepare()`.
- Showcase: the assembled Pages build served statically renders Bench, runs, files and the chat read-only, with only exported runs linked from the matrix.

## Not verified here

A full live run against a real model server, and the console on a physical phone.
