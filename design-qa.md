# Agent Lab console QA

Date: 2026-10-11
Result: from-scratch console redesign verified against the live API, a live model run, a live chat, replay, the read-only showcase, and phone width.

## Direction

The console is built around watching a small model work, not around browsing logs. It uses the field-notebook palette from Silas's own projects in a dark edition (forest and moss surfaces, paper text, sage, clay, ochre), Georgia display type and wide-tracked small-caps labels, all from fonts installed with Windows so the console works offline. An animated specimen shows agent state; a shimmering headline and activity feed narrate tool calls in the present tense while they run and the past tense once they return; the evaluator's verdict and first-pass versus repaired outcome lead the run page, and the model's own summary is shown last and labelled unverified.

## Automated evidence

- `node --test agent-lab/ui/test_ui_contract.mjs agent-lab/ui/test_narration.mjs`: 17 tests pass. They cover the capability contract (runs, chats, approvals, settings, providers, projects, skills), the endpoints the live source uses, the showcase refusing every mutating action, escaping of model and file text, reasoning staying out of the events pane, reduced motion, and the narration model's behavior on tool calls, failures, evaluator checks, repairs, compaction, phase tags, terminal states and chat grouping.
- `node --check` passes for `app.js`, `narration.js`, `source.js` and `specimen.js`.
- `python -m unittest discover -s agent-lab/ui -p 'test_*.py'`: includes complete event pages for replay and JavaScript MIME types for the console modules.

## Browser evidence

- Live API at 1440×900: a finished repaired run renders its verdict stamp, 13/13 checks, phase track, budget meter, files and the unverified model summary; the run list shows titles, reasoning levels and repaired badges.
- Live run: a File round-trip run started from the new-run dialog progressed turn by turn (rows appended, specimen thinking) and settled on "Passed on the first try" without a reload.
- Live chat: a new conversation showed a live "Thinking" line with a running timer, then the reply with its "Worked through N steps" disclosure.
- Replay: a recorded run replays from its complete event log with rows, phase tags, checks and the specimen animating; scrubbing and speed changes work.
- Details drawer: overview, files with preview, changes (review status and colored diff), filterable events and output. With the drawer open the run view reflows through container queries instead of truncating.
- Showcase: the assembled Pages site (`agent-lab/ui` plus `site/showcase`) loads in read-only mode on a non-loopback host, shows the showcase banner, lists the curated runs and auto-plays the first one; no API probe is made.
- Phone width (375×812): no horizontal overflow; navigation becomes an off-canvas sheet; the chamber, verdict, phases and activity stack cleanly.
- Browser console: no JavaScript errors in live or showcase mode.

## Known limits

- The model call is non-streaming, so between tool calls the console can only show "Thinking" with a timer and turn number, not text as it is generated. At low reasoning levels tool calls take milliseconds, so a 1.2 s poll mostly observes the thinking state.
- Replay paces events from their recorded timestamps, which have one-second resolution; events within the same second are spread out evenly.
- The showcase includes only the runs and chats named in `scripts/export_showcase.py`; files larger than 30 KB are not previewable there.
