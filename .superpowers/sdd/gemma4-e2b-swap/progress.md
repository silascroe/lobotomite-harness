# SDD ledger — plan: gemma4-e2b-swap

## Scope

Download the official Gemma 4 E2B Q4_0 GGUF, make the local launcher and prompt helper size-aware, switch the active Agent Lab config, and verify the model through the same harness path used for the E4B baseline.

## Rulings

- Keep the existing E4B model and its default launcher behavior intact; the swap must be reversible.
- Download only the text GGUF. The repository's multimodal projector is not used by this text-only harness.
- Treat a healthy `/health` response as necessary but insufficient; verify `/v1/models`, a direct completion, and a gated Agent Lab run.
- Repair integration defects only when they are observable in the swap path; do not tune harness behavior based on a single model's quality impression.

## Evidence ledger

- [x] Official E2B GGUF identified: `google/gemma-4-E2B-it-qat-q4_0-gguf`.
- [x] E2B GGUF downloaded to `models/Gemma4-E2B-GGUF`.
- [x] Downloaded file is 3,349,516,256 bytes and has a valid `GGUF` header.
- [x] Launcher and one-shot helper accept `E2B` and `E4B`; E4B remains the default.
- [x] Active harness config points at `Gemma-4-E2B-Q4_0`.
- [x] E4B stopped cleanly after verifying the process path and PID.
- [x] E2B server start succeeded after Smart App Control was disabled; `/health` and `/v1/models` identify the E2B GGUF.
- [x] Direct E2B completion succeeds: `E2B-LIVE-OK`, finish reason `stop`.
- [x] Standard gated run recorded a concrete limitation: 18 model calls, files created and validation passed, but no `plan` evidence or finish action.
- [x] Deep gated run recorded the same limitation: 18 model calls, files created and validation passed, but the generated project failed evaluator checks for responsive CSS and focus styling.
- [x] Focused regression tests pass: harness `32/32`, UI/server `16/16`; final diff check is clean.

## Final ruling

- Ruling: do not weaken workflow gates or retrofit a plan checkpoint from the harness — the failed runs are useful evidence that E2B is less reliable at this task, and changing the gates would corrupt the comparison; cost if wrong: E2B may be more viable with a model-specific prompt or larger turn budget.

Final review: self-review (no subagent tool); launcher, helper, config alignment, live endpoint, run artifacts, and regression outputs were reviewed independently.

