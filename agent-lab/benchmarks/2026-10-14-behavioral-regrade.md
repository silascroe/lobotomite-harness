# Behavioral re-grade of the October runs — 2026-10-14

The catalog checkers were rewritten to test behavior instead of source text. The static page and mini project are loaded in a real headless browser (installed Edge or Chrome, driven over the DevTools protocol by `agent-lab/checks/browser_probe.mjs`) and used: fields are typed into, buttons clicked, Tab and Enter pressed, the viewport shrunk to a 375px phone. The round-trip module is imported by Node and its `status` export read. The structured validator is run against the valid report and four invalid ones. No model was run for this report. The existing projects from the 2026-10-02 batch and the two 2026-10-11 sets were graded again with `agent-lab/benchmarks/regrade_runs.py`, which reads runs and never changes them.

## What changed in the checkers

| Task | Old pass condition (substring) | New pass condition (behavior) |
| --- | --- | --- |
| Static page | `<form`, `<label`, `addEventListener`, `:focus`, `@media` and similar strings present | page loads with no uncaught error; submitting two observations adds two cards with title, location and note, without a reload; the earlier card stays; a visible count goes 1 then 2; an empty-state message disappears; every Tab stop shows a visible change; nothing scrolls sideways on a phone; all text reaches 3:1 contrast; no remote requests |
| Mini project | `Signal Garden`, `<main`, `addEventListener`, `:focus` present; `node --check` passes | clicking the first button changes visible text; on a fresh load, Tab reaches it and Enter does the same; focus visible; phone layout fits |
| File round-trip | `export const status = "ok"` appears in the source | importing the module yields `status === "ok"` |
| Structured validation | validator exits 0 on the valid report and non-zero on `status: "bad"` | also non-zero on an empty `checks` array, on a check without a name, and on a missing `generated_for`, and prints something on success |

Each failed check now carries an `evidence` string saying what was observed (`clicking button.submit-btn "Submit Observation" reloaded the page instead of adding a card`, `no visible change when focused: input#title "Title"`), which the repair reminder passes to the model. A missing browser or Node, or the probe itself failing, is reported as an infrastructure finding, so a run errors instead of asking the model to fix something that is not in its project.

Two calls deserve stating. Contrast uses a 3:1 floor for all text, the WCAG large-text and UI-component level, not the 4.5:1 body-text level; a 2B model's color choices fail 4.5:1 often enough that the stricter bar would mostly measure palette taste. A first draft also required the mini project's status to be a live region (`aria-live` or `role=status`); all nine set B mini projects failed it and the task text never asks for it, so it was dropped rather than graded as a hidden requirement.

Re-grading also debugged the probe. A form that reloads the page could destroy the probe's script context between two polls; four static-page runs first came back with a protocol error as their "evidence". The probe now treats a lost context as a navigation, waits briefly for reloads that land after a submit handler has already run, and reports any protocol error as infrastructure. On Windows the browser's port file could also be read while still locked, which crashed two probes under parallel load. The numbers below come from a clean pass after both fixes, with no run left ungraded.

## Results

73 runs had a recorded evaluation and were graded again; 11 more had none (they stopped before finishing) and none of those pass now except one 2026-10-02 run.

| Task | Graded runs | Passed then | Pass now | Pass then, fail now | Fail then, pass now |
| --- | --- | --- | --- | --- | --- |
| Static page | 17 | 6 | 4 | 5 | 3 |
| File round-trip | 20 | 20 | 20 | 0 | 0 |
| Structured validation | 15 | 10 | 0 | 10 | 0 |
| Mini project | 21 | 15 | 15 | 3 | 3 |

The 2026-10-11 comparison, re-graded:

| | Set A then | Set A now | Set B then | Set B now |
| --- | --- | --- | --- | --- |
| Passed | 17/36 | 17/36 | 26/36 | **18/36** |
| First-evaluation passes that still pass | 13 | 9 | 17 | 10 |
| Repaired passes that still pass | 4 | 3 | 9 | 7 |
| Static page | 2/9 | 2/9 | 3/9 | 2/9 |
| File round-trip | 9/9 | 9/9 | 9/9 | 9/9 |
| Structured validation | 2/9 | 0/9 | 6/9 | 0/9 |
| Mini project | 4/9 | 6/9 | 8/9 | 7/9 |

The headline improvement from set A to set B does not survive. Overall it was 17 vs 26 (p = 0.054); it is now 17 vs 18 (Fisher exact, p = 1.0). Most of set B's gain was structured-validation validators that passed the old checker and check less than the task asks. Repair success, the best-supported effect in the earlier report (4/18 vs 9/15, p = 0.038), is 3/18 vs 7/15 counting only repairs whose result still passes (p = 0.13): still pointing the same way, no longer significant. The 2026-10-02 batch, recorded as 8 of 12 and corrected by the audit to 10 of 12, is 5 of 12.

## What the old checkers let through

Structured validation is 0 of 15 now, and every one of the ten former passes fails for the same reason: the validator does not check that each check has a name, does not check `generated_for`, or neither. The task says the validator "checks those fields". This is a real omission, not checker pedantry, and the old checker could not see it because it only tried one bad report.

Static page failures that the old checker passed are genuine bugs found by reading the projects:

- `matrix-20261011-205901-001-standard` looks up `observationForm`, `observationsList` and `count` while the HTML has `observation-form`, `observation-list` and `observation-count`. The script crashes on load and submitting the form reloads the page. Every substring was present.
- `matrix-20261011-201925-001-off` clears its list with `innerHTML` when it first renders, deleting the empty-state message that lived inside it, so the message never shows; it also scrolls sideways on a phone. `-185251-001-off` does the opposite: its empty-state message stays on screen beside the cards.
- `matrix-20261011-192057-001-deep`'s submit button is 2.36:1 against its background, and `-185251-001-off`'s card titles are 2.43:1.
- Three mini projects (`-072910-004-deep`, `-194103-004-deep`, `-203757-004-off`) are 391–395px wide on a 375px phone and scroll sideways.

Two runs that failed both times failed the old checker for the wrong reason. `-205901-001-off` puts the same `id` on a section and the form, so `form.reset` is not a function and no card appears; `-201925-001-standard` styles a `.body` class instead of `body`, leaving near-white text on white (1.18:1). The old checker objected only to a missing `:focus` rule. One line of CSS would have passed both broken pages.

The six fail-then-pass runs had failed the old checker only on its focus-style, responsive-CSS or `<main>` substrings. Five are pages with no `:focus` or `@media` rule that still show the browser's default focus ring and fit a phone; the old checker failed working pages. The sixth, `matrix-20261011-194103-004-standard`, was edited after its last evaluation (its recorded failure includes a missing `<main>`, which the final files have); the re-grade judges the final files, which is what a reader would open.

## Limits

These are the same projects, not new runs; models were never shown the new findings, so this measures how the old work holds up, not how the harness does with behavioral feedback. A new matrix on the new checkers is the real test. The probe uses fixed test inputs and one primary button; a page that needs a different interaction (a second form, a select, a confirmation step) can be misgraded, and the evidence string is the place to check. Grading a static page takes about 7 seconds instead of a fraction of one, which the evaluator timeout (`evaluator_timeout_seconds`, 90 by default) covers.

Raw results: `agent-lab/benchmarks/results/regrade-20261014-214904.json` (ignored by Git, like other generated results). Reproduce with:

```powershell
& $py agent-lab/benchmarks/regrade_runs.py matrix-20261002-072910 matrix-20261011-185251 matrix-20261011-192057 matrix-20261011-194103 matrix-20261011-201925 matrix-20261011-203757 matrix-20261011-205901
```
