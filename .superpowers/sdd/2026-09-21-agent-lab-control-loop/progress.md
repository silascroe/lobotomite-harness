# SDD ledger — plan: docs/superpowers/plans/2026-09-21-agent-lab-control-loop.md

## Baseline

- Existing E2B model swap is uncommitted user work and must be preserved.
- Existing workflow gates require inspect, plan, implement, and verify evidence.
- Benchmark and interactive loops currently retry protocol/tool/finish problems
  until their global turn limit.
- `.research/agent-reference/aider` is a shallow read-only reference checkout.
- `.research/agent-reference/openai-codex` required sparse checkout on Windows
  because its full tree contains a path rejected by the Windows filename limit.

## Rulings

- Use a shared pure recovery controller rather than two ad hoc retry systems.
- Default to one repair attempt for the same failure and one corrective turn for
  the same consecutive action.
- Never fake workflow evidence or automatically resume interrupted jobs.
- Stop benchmark loops as blocked when recovery is exhausted; keep interactive
  sessions usable after reporting the exhausted condition.
- Accept explicit late plan evidence after automatic phase advancement without
  rewinding the visible phase; record the ordering as `workflow_late_evidence`.

## Interface ledger

| Surface | Current contract | Planned change | Compatibility |
| --- | --- | --- | --- |
| `control_loop.py` | absent | pure failure/action recovery policy | new internal module |
| benchmark summary | workflow/evidence only | add recovery snapshot and blocked reason | additive JSON |
| session metadata | job/workflow only | add recovery snapshot | additive JSON |
| events | tool/model/workflow events | add recovery lifecycle events | additive JSONL |

## Execution

- [x] Task 1: controller and unit tests
- [x] Task 2: benchmark integration and tests
- [x] Task 3: interactive integration and tests
- [x] Task 4: docs/API surface
- [x] Task 5: full verification and E2B smoke run

## Verification evidence

- Controller tests: 7/7 passed.
- Full harness suite: 43/43 passed with the bundled Python runtime.
- Full UI/server suite: 19/19 passed with the bundled Python runtime.
- Python compilation: passed for the modified harness and UI modules.
- UI contract suite: 15/15 passed with the bundled Node runtime.
- `git diff --check`: passed; `config.json` parsed successfully.
- Live model health: `http://127.0.0.1:8080/health` returned `ok`; the endpoint
  served `Gemma-4-E2B-Q4_0` with an 8192-token context and Q4_0 quantization.
- `run-control-loop-e2b-20260921`: blocked after 8 model calls when repeated
  finish rejection proved the plan gate was still missing. This exposed the
  late-plan state-machine edge case.
- `run-control-loop-late-plan-e2b-20260921`: late plan evidence was accepted;
  the evaluator then correctly reported missing focus styling, and the model's
  identical malformed `apply_patch` was blocked before a third dispatch. The
  run stopped at 13 model calls instead of burning all 18 turns. It remained
  blocked, as it should.

## Final review

Self-review completed without a subagent: no workflow gate was weakened, no
duplicate tool action reaches dispatch after detection, interactive recovery
state is persisted/restored, reference checkouts remain ignored and outside the
runtime path, and the pre-existing E2B swap files remain untouched except for
the requested additive config/docs changes.

## Review

Complete. Final review checked for gate weakening, duplicate dispatch, stale
worker races, missing persistence, and claims unsupported by fresh command
output; the follow-up edit-recovery slice was verified separately against a
live E2B benchmark.

